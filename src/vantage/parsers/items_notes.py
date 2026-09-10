"""Character item tracker and cross-linked personal notes."""

from __future__ import annotations

from html import escape
import re

from PySide6.QtCore import QSignalBlocker, QStringListModel, Qt, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton,
    QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.item_journal import (
    REFERENCE_RE, ItemJournal, parse_inventory_dump, reference_token)
from vantage.helpers.parser import ParserWindow
from vantage.parsers.maps.mapdata import MapData


class ReferenceEditor(QPlainTextEdit):
    """Plain, portable note editor with a compact @ reference picker."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries = []
        self._model = QStringListModel(self)
        self.completer = QCompleter(self._model, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated.connect(self._insert_completion)

    def set_reference_entries(self, entries):
        self._entries = sorted(set(entries), key=str.casefold)
        self._model.setStringList(self._entries)

    def _active_prefix(self):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        block = cursor.selectedText()
        relative = self.textCursor().positionInBlock()
        match = re.search(r"@([^@\[\]\r\n]*)$", block[:relative])
        return match.group(1).strip() if match else None

    def _insert_completion(self, display):
        kind, separator, label = str(display).partition(" · ")
        if not separator:
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock,
                            QTextCursor.MoveMode.KeepAnchor)
        left = cursor.selectedText()
        match = re.search(r"@([^@\[\]\r\n]*)$", left)
        if not match:
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Left,
                            QTextCursor.MoveMode.KeepAnchor,
                            len(match.group(0)))
        cursor.insertText(reference_token(kind, label))
        self.setTextCursor(cursor)

    def keyPressEvent(self, event: QKeyEvent):
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (
                Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape,
                Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            event.ignore()
            return
        super().keyPressEvent(event)
        prefix = self._active_prefix()
        if prefix is None:
            popup.hide()
            return
        self.completer.setCompletionPrefix(prefix)
        rectangle = self.cursorRect()
        rectangle.setWidth(max(320, popup.sizeHintForColumn(0) + 24))
        self.completer.complete(rectangle)


class ItemsNotes(ParserWindow):
    """Track imported P99 possessions and keep durable linked notes."""

    name = "items_notes"
    _allow_clickthrough = False

    def __init__(self, market, quests, journal=None):
        super().__init__()
        self._market = market
        self._quests = quests
        self._journal = journal or ItemJournal()
        self._current_note_id = ""
        self._loading_note = False
        self._visible_rows = []
        self.setWindowTitle("Items & Notes · Vantage")
        self._title.setText("Items & Notes")
        self._note_save_timer = QTimer(self)
        self._note_save_timer.setSingleShot(True)
        self._note_save_timer.setInterval(500)
        self._note_save_timer.timeout.connect(self._save_current_note)
        self._quest_catalog_timer = QTimer(self)
        self._quest_catalog_timer.setInterval(700)
        self._quest_catalog_timer.timeout.connect(self._sync_quest_references)
        self._build_ui()
        self._new_note_shortcut = QShortcut(QKeySequence.StandardKey.New, self)
        self._new_note_shortcut.activated.connect(self._new_note)
        self._save_note_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._save_note_shortcut.activated.connect(self._save_current_note)
        self._refresh_everything()

    def _build_ui(self):
        self.tabs = QTabWidget()
        self.tabs.setObjectName("ItemsNotesTabs")
        self.tabs.setAccessibleName("Items and notes sections")
        self.tabs.addTab(self._items_page(), "Items")
        self.tabs.addTab(self._notes_page(), "Notes")
        self.tabs.setTabToolTip(0, "Track inventory and bank dumps by character")
        self.tabs.setTabToolTip(1, "Keep local notes with linked P99 references")
        self.content.addWidget(self.tabs, 1)

    def _items_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        help_text = QLabel(
            "In EverQuest use /outputfile inventory Character-Inventory.txt. "
            "That one P99 dump includes carried and bank items; Vantage only reads it.")
        help_text.setObjectName("ItemsNotesHelp")
        help_text.setWordWrap(True)
        help_text.setAccessibleName("Inventory dump instructions")
        layout.addWidget(help_text)

        top = QFrame()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(5)
        self.character_selector = QComboBox()
        self.character_selector.setAccessibleName("Tracked character")
        self.character_selector.setToolTip(
            "Show all tracked characters or one imported inventory snapshot")
        self.character_selector.currentIndexChanged.connect(self._refresh_items)
        top_layout.addWidget(self.character_selector, 1)
        self.import_button = QPushButton("Import dump")
        self.import_button.setIcon(game_icon("import"))
        self.import_button.setAccessibleName("Import P99 inventory dump")
        self.import_button.setToolTip(
            "Read a Location, Name, ID, Count, Slots inventory output file")
        self.import_button.clicked.connect(self._import_dump)
        top_layout.addWidget(self.import_button)
        self.restore_button = QPushButton("Restore prior")
        self.restore_button.setIcon(game_icon("refresh"))
        self.restore_button.setAccessibleName("Restore previous character import")
        self.restore_button.setToolTip(
            "Restore the previous saved dump for the selected character")
        self.restore_button.clicked.connect(self._restore_previous)
        top_layout.addWidget(self.restore_button)
        layout.addWidget(top)

        filters = QFrame()
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(5)
        self.item_search = QLineEdit()
        self.item_search.setPlaceholderText("Search tracked items or locations…")
        self.item_search.setClearButtonEnabled(True)
        self.item_search.setAccessibleName("Search tracked items")
        self.item_search.textChanged.connect(self._refresh_items)
        clear = self.item_search.findChild(QToolButton)
        if clear:
            clear.setAccessibleName("Clear tracked item search")
            clear.setToolTip("Clear the tracked item search")
        filter_layout.addWidget(self.item_search, 1)
        self.location_filter = QComboBox()
        self.location_filter.addItems(
            ("All locations", "Equipped", "Inventory", "Bags", "Bank", "Shared Bank"))
        self.location_filter.setAccessibleName("Item location filter")
        self.location_filter.currentIndexChanged.connect(self._refresh_items)
        filter_layout.addWidget(self.location_filter)
        layout.addWidget(filters)

        self.item_table = QTableWidget(0, 5)
        self.item_table.setHorizontalHeaderLabels(
            ("Item", "Character", "Location", "Qty", "Item ID"))
        for column, tooltip in enumerate((
                "Imported item name", "Character snapshot", "Exact dump location",
                "Tracked quantity", "Project 1999 item identifier")):
            self.item_table.horizontalHeaderItem(column).setToolTip(tooltip)
        self.item_table.setAccessibleName("Tracked EverQuest items")
        self.item_table.setAccessibleDescription(
            "Sortable imported possessions; double-click an item to open its Vantage card")
        self.item_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.item_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.item_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.item_table.setSortingEnabled(True)
        self.item_table.setAlternatingRowColors(True)
        self.item_table.verticalHeader().setVisible(False)
        header = self.item_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.item_table.itemDoubleClicked.connect(
            lambda *_args: self._open_selected_item())
        self.item_table.itemSelectionChanged.connect(self._sync_item_actions)
        layout.addWidget(self.item_table, 1)

        actions = QFrame()
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(5)
        self.item_status = QLabel("No inventory imported")
        self.item_status.setObjectName("ItemsNotesStatus")
        self.item_status.setAccessibleName("Tracked item status")
        action_layout.addWidget(self.item_status, 1)
        self.open_item_button = QPushButton("Open item")
        self.open_item_button.setIcon(game_icon("market"))
        self.open_item_button.clicked.connect(self._open_selected_item)
        action_layout.addWidget(self.open_item_button)
        self.quantity_button = QPushButton("Set quantity")
        self.quantity_button.setIcon(game_icon("edit"))
        self.quantity_button.clicked.connect(self._set_quantity)
        action_layout.addWidget(self.quantity_button)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setIcon(game_icon("delete"))
        self.remove_button.clicked.connect(self._remove_item)
        action_layout.addWidget(self.remove_button)
        self.undo_button = QPushButton("Undo")
        self.undo_button.setIcon(game_icon("refresh"))
        self.undo_button.setToolTip("Undo the last item or note change in this session")
        self.undo_button.clicked.connect(self._undo)
        action_layout.addWidget(self.undo_button)
        layout.addWidget(actions)
        return page

    def _notes_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)

        toolbar = QFrame()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(5)
        self.new_note_button = QPushButton("New note")
        self.new_note_button.setIcon(game_icon("add"))
        self.new_note_button.clicked.connect(self._new_note)
        toolbar_layout.addWidget(self.new_note_button)
        self.delete_note_button = QPushButton("Delete note")
        self.delete_note_button.setIcon(game_icon("delete"))
        self.delete_note_button.clicked.connect(self._delete_note)
        toolbar_layout.addWidget(self.delete_note_button)
        self.note_status = QLabel(
            "Type @ to link an Item, Quest, or Zone · notes save automatically")
        self.note_status.setObjectName("ItemsNotesStatus")
        self.note_status.setAccessibleName("Note save status")
        toolbar_layout.addWidget(self.note_status, 1)
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.note_list = QListWidget()
        self.note_list.setMinimumWidth(185)
        self.note_list.setAccessibleName("Saved notes")
        self.note_list.currentItemChanged.connect(self._note_selected)
        splitter.addWidget(self.note_list)

        editor_frame = QFrame()
        editor_layout = QVBoxLayout(editor_frame)
        editor_layout.setContentsMargins(4, 0, 0, 0)
        editor_layout.setSpacing(5)
        self.note_title = QLineEdit()
        self.note_title.setPlaceholderText("Note title")
        self.note_title.setAccessibleName("Current note title")
        self.note_title.textChanged.connect(self._note_changed)
        editor_layout.addWidget(self.note_title)
        self.note_tabs = QTabWidget()
        self.note_editor = ReferenceEditor()
        self.note_editor.setPlaceholderText(
            "Write anything. Type @, then search for an item, quest, or zone…")
        self.note_editor.setAccessibleName("Current note text")
        self.note_editor.setToolTip(
            "Type @ to insert an Item, Quest, or Zone reference · Ctrl+S saves")
        self.note_editor.textChanged.connect(self._note_changed)
        self.note_preview = QTextBrowser()
        self.note_preview.setOpenLinks(False)
        self.note_preview.setOpenExternalLinks(False)
        self.note_preview.setAccessibleName("Clickable note preview")
        self.note_preview.setToolTip(
            "Select a gold reference to open its internal Vantage information card")
        self.note_preview.anchorClicked.connect(self._reference_clicked)
        self.note_tabs.addTab(self.note_editor, "Write")
        self.note_tabs.addTab(self.note_preview, "Preview links")
        self.note_tabs.setTabToolTip(0, "Edit plain portable note text and @ references")
        self.note_tabs.setTabToolTip(1, "Open Item, Quest, and Zone references")
        self.note_tabs.currentChanged.connect(self._note_tab_changed)
        editor_layout.addWidget(self.note_tabs, 1)
        splitter.addWidget(editor_frame)
        splitter.setSizes((210, 650))
        layout.addWidget(splitter, 1)
        return page

    def _characters(self):
        return sorted(self._journal.data["characters"], key=str.casefold)

    def _refresh_everything(self):
        selected = self.character_selector.currentData()
        with QSignalBlocker(self.character_selector):
            self.character_selector.clear()
            self.character_selector.addItem("All characters", "")
            for character in self._characters():
                self.character_selector.addItem(character, character)
            index = self.character_selector.findData(selected)
            self.character_selector.setCurrentIndex(max(0, index))
        self._refresh_items()
        self._refresh_notes()
        self._refresh_references()

    def _refresh_references(self):
        item_names = {row["name"] for row in self._journal.rows()}
        item_names.update(item.name for item in self._market._gear_model.items)
        entries = [f"Item · {name}" for name in item_names if name]
        entries.extend(f"Zone · {name.title()}" for name in MapData.get_zone_dict())
        entries.extend(f"Quest · {name}" for name in self._quests._catalog)
        self.note_editor.set_reference_entries(entries)

    def set_quest_catalog(self, names):
        existing = list(self.note_editor._entries)
        existing.extend(f"Quest · {name}" for name in names if str(name).strip())
        self.note_editor.set_reference_entries(existing)

    def _sync_quest_references(self):
        if self._quests._catalog:
            self._refresh_references()
            self._quest_catalog_timer.stop()

    def _import_dump(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import EverQuest inventory dump", "",
            "Inventory dumps (*.txt *.tsv *.csv);;All files (*.*)")
        if not path:
            return
        try:
            snapshot = parse_inventory_dump(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Inventory not imported", str(error))
            return
        existing = snapshot["character"] in self._journal.data["characters"]
        if existing and QMessageBox.question(
                self, "Replace character snapshot",
                f"Replace {snapshot['character']}'s tracked items with this dump? "
                "The current snapshot remains available under Restore prior.") != \
                QMessageBox.StandardButton.Yes:
            return
        self._journal.import_snapshot(snapshot)
        self._refresh_everything()
        index = self.character_selector.findData(snapshot["character"])
        self.character_selector.setCurrentIndex(max(0, index))
        self.item_status.setText(
            f"Imported {len(snapshot['items']):,} rows from {snapshot['source']}")

    def _refresh_items(self):
        character = self.character_selector.currentData() or ""
        query = self.item_search.text().strip().casefold()
        location = self.location_filter.currentText()
        rows = []
        for row in self._journal.rows(character):
            haystack = f"{row['name']} {row['location']} {row['item_id']}".casefold()
            if query and query not in haystack:
                continue
            if location != "All locations" and row.get("group") != location:
                continue
            rows.append(row)
        self._visible_rows = rows
        self.item_table.setSortingEnabled(False)
        self.item_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (row["name"], row["character"], row["location"],
                      str(row["quantity"]), row["item_id"])
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.ItemDataRole.UserRole,
                             (row["character"], row["key"]))
                if column == 3:
                    cell.setData(Qt.ItemDataRole.DisplayRole, int(row["quantity"]))
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight |
                                          Qt.AlignmentFlag.AlignVCenter)
                self.item_table.setItem(row_index, column, cell)
        self.item_table.setSortingEnabled(True)
        self.item_status.setText(
            f"{len(rows):,} shown · {len(self._journal.rows(character)):,} tracked")
        self.restore_button.setEnabled(bool(
            character and self._journal.data["history"].get(character)))
        self._sync_item_actions()

    def _selected_identity(self):
        row = self.item_table.currentRow()
        cell = self.item_table.item(row, 0) if row >= 0 else None
        return cell.data(Qt.ItemDataRole.UserRole) if cell else None

    def _selected_row(self):
        identity = self._selected_identity()
        if not identity:
            return None
        character, key = identity
        return next((row for row in self._journal.rows(character)
                     if row.get("key") == key), None)

    def _sync_item_actions(self):
        enabled = self._selected_identity() is not None
        for button in (self.open_item_button, self.quantity_button, self.remove_button):
            button.setEnabled(enabled)
        self.undo_button.setEnabled(self._journal._undo is not None)

    def _open_selected_item(self):
        row = self._selected_row()
        if row:
            self._market._show_wiki_item_name(row["name"])

    def _set_quantity(self):
        row = self._selected_row()
        if not row:
            return
        quantity, accepted = QInputDialog.getInt(
            self, "Set item quantity", row["name"], int(row["quantity"]),
            1, 2_000_000_000, 1)
        if accepted and self._journal.set_quantity(
                row["character"], row["key"], quantity):
            self._refresh_items()

    def _remove_item(self):
        row = self._selected_row()
        if not row:
            return
        if QMessageBox.question(
                self, "Remove tracked item",
                f"Remove {row['name']} from {row['character']}?\n\n"
                "This changes only Vantage's local copy and can be undone.") != \
                QMessageBox.StandardButton.Yes:
            return
        if self._journal.remove_item(row["character"], row["key"]):
            self._refresh_items()

    def _restore_previous(self):
        character = self.character_selector.currentData() or ""
        if character and self._journal.restore_previous_import(character):
            self._refresh_everything()
            self.item_status.setText(f"Restored the prior import for {character}")

    def _undo(self):
        if self._journal.undo():
            self._refresh_everything()
            self.item_status.setText("Last local change undone")

    def _refresh_notes(self):
        selected = self._current_note_id
        with QSignalBlocker(self.note_list):
            self.note_list.clear()
            for note in self._journal.data["notes"]:
                item = QListWidgetItem(note.get("title") or "Untitled note")
                item.setData(Qt.ItemDataRole.UserRole, note.get("id"))
                item.setToolTip(f"Last saved {note.get('updated_at', '')}")
                self.note_list.addItem(item)
            match = next((index for index in range(self.note_list.count())
                          if self.note_list.item(index).data(
                              Qt.ItemDataRole.UserRole) == selected), -1)
            if match >= 0:
                self.note_list.setCurrentRow(match)
        self.delete_note_button.setEnabled(bool(self._current_note_id))

    def _new_note(self):
        self._save_current_note()
        try:
            self._current_note_id = self._journal.upsert_note(
                "", "New note", "")
        except ValueError as error:
            QMessageBox.warning(self, "Note not created", str(error))
            return
        self._refresh_notes()
        self._select_note_id(self._current_note_id)
        self._loading_note = True
        self.note_title.setText("New note")
        self.note_editor.clear()
        self.note_preview.clear()
        self._loading_note = False
        self.note_title.selectAll()
        self.note_title.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _select_note_id(self, note_id):
        for index in range(self.note_list.count()):
            item = self.note_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == note_id:
                self.note_list.setCurrentItem(item)
                return

    def _note_selected(self, current, _previous):
        if self._loading_note:
            return
        self._save_current_note()
        note_id = current.data(Qt.ItemDataRole.UserRole) if current else ""
        note = next((value for value in self._journal.data["notes"]
                     if value.get("id") == note_id), None)
        self._loading_note = True
        try:
            self._current_note_id = note_id or ""
            self.note_title.setText(note.get("title", "") if note else "")
            self.note_editor.setPlainText(note.get("text", "") if note else "")
            self._render_preview()
        finally:
            self._loading_note = False
        self.delete_note_button.setEnabled(bool(note))

    def _note_changed(self):
        if self._loading_note:
            return
        if not self._current_note_id:
            try:
                self._current_note_id = self._journal.upsert_note(
                    "", self.note_title.text(), self.note_editor.toPlainText())
            except ValueError as error:
                self.note_status.setText(str(error))
                return
            self._refresh_notes()
            self._select_note_id(self._current_note_id)
            self.note_status.setText("Saving…")
            self._note_save_timer.start()
            return
        self.note_status.setText("Saving…")
        self._note_save_timer.start()

    def _save_current_note(self):
        if not self._current_note_id or self._loading_note:
            return
        try:
            self._journal.upsert_note(
                self._current_note_id, self.note_title.text(),
                self.note_editor.toPlainText())
        except ValueError as error:
            self.note_status.setText(str(error))
            return
        self.note_status.setText("Saved locally")
        current = self.note_list.currentItem()
        if current:
            current.setText(self.note_title.text().strip() or "Untitled note")
        self._render_preview()

    def _delete_note(self):
        if not self._current_note_id:
            return
        if QMessageBox.question(
                self, "Delete note",
                "Delete this note? You can use Undo immediately afterward.") != \
                QMessageBox.StandardButton.Yes:
            return
        self._note_save_timer.stop()
        self._journal.delete_note(self._current_note_id)
        self._current_note_id = ""
        self._refresh_notes()
        self._loading_note = True
        self.note_title.clear()
        self.note_editor.clear()
        self.note_preview.clear()
        self._loading_note = False

    def _note_tab_changed(self, index):
        if self.note_tabs.tabText(index) == "Preview links":
            self._save_current_note()
            self._render_preview()

    def _render_preview(self):
        text = self.note_editor.toPlainText()
        parts = []
        cursor = 0
        for match in REFERENCE_RE.finditer(text):
            parts.append(escape(text[cursor:match.start()]))
            kind = match.group(1).title()
            label = match.group(2).strip()
            query = QUrlQuery()
            query.addQueryItem("kind", kind)
            query.addQueryItem("label", label)
            url = QUrl("vantage-ref://open")
            url.setQuery(query)
            parts.append(
                f'<a href="{escape(url.toString(), quote=True)}">'
                f'{escape(kind)}: {escape(label)}</a>')
            cursor = match.end()
        parts.append(escape(text[cursor:]))
        body = "".join(parts).replace("\n", "<br>")
        self.note_preview.setHtml(
            "<style>a{color:#e4c36f;text-decoration:none;font-weight:600;}"
            "body{color:#d7e3e6;line-height:1.45;}</style>" +
            (body or "<i>Nothing to preview yet.</i>"))

    def _reference_clicked(self, url):
        query = QUrlQuery(url)
        kind = query.queryItemValue("kind").title()
        label = query.queryItemValue("label").strip()
        if kind == "Item":
            self._market._show_wiki_item_name(label)
        elif kind in {"Quest", "Zone"}:
            self._market._show_wiki_entity(label, label, kind.casefold())

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_references()
        if not self._quests._catalog:
            if not self._quests._catalog_loading:
                self._quests._fetch_catalog()
            self._quest_catalog_timer.start()

    def closeEvent(self, event):
        self._save_current_note()
        super().closeEvent(event)

    def parse(self, _timestamp, _text):
        """Items & Notes never inspects live logs."""
