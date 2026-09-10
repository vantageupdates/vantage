"""Character item tracker and cross-linked personal notes."""

from __future__ import annotations

from html import escape
from datetime import datetime
from pathlib import Path
import re

from PySide6.QtCore import QPoint, QSignalBlocker, QStringListModel, Qt, QTimer, QUrl, QUrlQuery
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QKeyEvent, QKeySequence,
    QShortcut, QTextCursor)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QCompleter, QFrame,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QSizeGrip, QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QToolButton,
    QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import game_icon
from vantage.helpers.item_journal import (
    REFERENCE_RE, ItemJournal, discover_inventory_dumps,
    parse_inventory_dump, reference_token)
from vantage.helpers.friends_manager import everquest_root_from_logs
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


class _StickyDragHandle(QLabel):
    """Keyboard-neutral drag surface for a frameless sticky note."""

    def __init__(self, window):
        super().__init__("STICKY NOTE", window)
        self._host_window = window
        self._origin = None
        self.setObjectName("StickyNoteDragHandle")
        self.setAccessibleName("Sticky note move handle")
        self.setToolTip(
            "Drag to move · Alt+Arrow moves with the keyboard")
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = (
                event.globalPosition().toPoint() - self._host_window.pos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._origin is not None and
                event.buttons() & Qt.MouseButton.LeftButton):
            self._host_window.move(
                event.globalPosition().toPoint() - self._origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class StickyNoteWindow(QWidget):
    """Small always-on-top editor backed by one Items & Notes record."""

    def __init__(self, owner, note):
        super().__init__(None, Qt.WindowType.Tool |
                        Qt.WindowType.WindowStaysOnTopHint |
                        Qt.WindowType.FramelessWindowHint)
        self.owner = owner
        self.note_id = str(note.get("id") or "")
        self._loading = False
        self._quitting = False
        self.setObjectName("StickyNoteWindow")
        self.setAccessibleName("Floating sticky note")
        self.setAccessibleDescription(
            "Borderless note. Alt plus Arrow moves it; Control plus Alt plus "
            "Arrow resizes it; add Shift for one-pixel adjustments.")
        self.setWindowIcon(game_icon("ph-backpack"))
        self.setMinimumSize(240, 160)
        self.resize(320, 250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 7)
        layout.setSpacing(5)
        chrome = QHBoxLayout()
        chrome.setContentsMargins(0, 0, 0, 0)
        chrome.setSpacing(4)
        self.drag_handle = _StickyDragHandle(self)
        chrome.addWidget(self.drag_handle, 1)
        self.close_button = QToolButton()
        self.close_button.setObjectName("StickyNoteClose")
        self.close_button.setText("×")
        self.close_button.setAccessibleName("Hide this sticky note")
        self.close_button.setToolTip(
            "Hide this floating note; it remains saved in Items & Notes")
        self.close_button.clicked.connect(self.close)
        chrome.addWidget(self.close_button)
        layout.addLayout(chrome)
        self.title = QLineEdit()
        self.title.setObjectName("StickyNoteTitle")
        self.title.setPlaceholderText("Note title")
        self.title.setAccessibleName("Sticky note title")
        self.title.setAccessibleDescription(
            "Alt plus Arrow moves this note; Control plus Alt plus Arrow resizes it")
        self.title.textChanged.connect(self._changed)
        layout.addWidget(self.title)

        self.editor = ReferenceEditor()
        self.editor.setObjectName("StickyNoteEditor")
        self.editor.setPlaceholderText(
            "Write a note. Type @ to link an item, quest, or zone…")
        self.editor.setAccessibleName("Sticky note text")
        self.editor.setTabChangesFocus(True)
        self.editor.setToolTip(
            "This is the same note shown in Items & Notes · changes save automatically")
        self.editor.textChanged.connect(self._changed)
        layout.addWidget(self.editor, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(5)
        self.status = QLabel("Saved")
        self.status.setObjectName("StickyNoteStatus")
        self.status.setAccessibleName("Sticky note save status")
        self.status.setAccessibleDescription(
            "Saved locally and ready for Device Sync when paired PCs are online")
        footer.addWidget(self.status, 1)
        self.open_button = QPushButton("Open")
        self.open_button.setIcon(game_icon("ph-backpack"))
        self.open_button.setAccessibleName("Open this sticky note in Items and Notes")
        self.open_button.setToolTip(
            "Open the full Notes workspace and select this same note")
        self.open_button.clicked.connect(self._open_in_notes)
        footer.addWidget(self.open_button)
        self.unpin_button = QPushButton("Unpin")
        self.unpin_button.setIcon(game_icon("minimize"))
        self.unpin_button.setAccessibleName(
            "Stop showing this note as a floating sticky note")
        self.unpin_button.setToolTip(
            "Remove the floating sticky window but keep the note saved")
        self.unpin_button.clicked.connect(self._return_to_notes)
        footer.addWidget(self.unpin_button)
        self.resize_grip = QSizeGrip(self)
        self.resize_grip.setAccessibleName("Resize sticky note")
        self.resize_grip.setToolTip(
            "Drag to resize · Ctrl+Alt+Arrow resizes with the keyboard")
        footer.addWidget(self.resize_grip)
        layout.addLayout(footer)

        self._keyboard_geometry_shortcuts = []
        directions = {
            "Left": (-1, 0), "Right": (1, 0),
            "Up": (0, -1), "Down": (0, 1),
        }
        for key, (dx, dy) in directions.items():
            for prefix, resize, step in (
                    ("Alt", False, 10), ("Alt+Shift", False, 1),
                    ("Ctrl+Alt", True, 10),
                    ("Ctrl+Alt+Shift", True, 1)):
                shortcut = QShortcut(QKeySequence(f"{prefix}+{key}"), self)
                shortcut.setContext(
                    Qt.ShortcutContext.WidgetWithChildrenShortcut)
                shortcut.activated.connect(
                    lambda x=dx, y=dy, amount=step, sizing=resize:
                    self._keyboard_geometry_change(x, y, amount, sizing))
                self._keyboard_geometry_shortcuts.append(shortcut)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(350)
        self._save_timer.timeout.connect(self._save)
        self._geometry_timer = QTimer(self)
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(250)
        self._geometry_timer.timeout.connect(self._save_geometry)
        QApplication.instance().aboutToQuit.connect(self._prepare_to_quit)
        self.apply_note(note)
        self._restore_geometry(note.get("geometry"))

    def _keyboard_geometry_change(self, dx, dy, step, resize):
        """Move or resize the frameless note without requiring a pointer."""
        if resize:
            self.resize(
                max(self.minimumWidth(), self.width() + dx * step),
                max(self.minimumHeight(), self.height() + dy * step))
            message = f"Sticky note size {self.width()} by {self.height()}"
        else:
            screen = QApplication.screenAt(self.frameGeometry().center()) \
                or QApplication.primaryScreen()
            target = self.pos() + QPoint(dx * step, dy * step)
            if screen is not None:
                area = screen.availableGeometry()
                target.setX(max(
                    area.left(), min(
                        target.x(), area.right() - self.width() + 1)))
                target.setY(max(
                    area.top(), min(
                        target.y(), area.bottom() - self.height() + 1)))
            self.move(target)
            message = f"Sticky note position {self.x()}, {self.y()}"
        self.status.setText(message)
        self.status.setAccessibleDescription(message)
        try:
            QAccessible.updateAccessibility(
                QAccessibleAnnouncementEvent(self.status, message))
        except (AttributeError, RuntimeError, TypeError):
            pass
        self._geometry_timer.start()

    def _restore_geometry(self, geometry):
        if (isinstance(geometry, list) and len(geometry) == 4 and
                all(isinstance(value, int) for value in geometry)):
            self.setGeometry(*geometry)
        else:
            offset = 28 * (len(self.owner._sticky_windows) % 6)
            self.move(self.owner.x() + 40 + offset, self.owner.y() + 55 + offset)
        screen = QApplication.screenAt(self.frameGeometry().center()) \
            or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        width = min(self.width(), area.width())
        height = min(self.height(), area.height())
        x = max(area.left(), min(self.x(), area.right() - width + 1))
        y = max(area.top(), min(self.y(), area.bottom() - height + 1))
        self.setGeometry(x, y, width, height)

    def apply_note(self, note):
        """Refresh from Notes or Device Sync without moving the text cursor."""
        title = str(note.get("title") or "Untitled note")
        text = str(note.get("text") or "")
        self._loading = True
        try:
            if self.title.text() != title:
                with QSignalBlocker(self.title):
                    self.title.setText(title)
            if self.editor.toPlainText() != text:
                with QSignalBlocker(self.editor):
                    self.editor.setPlainText(text)
            self.setWindowTitle(f"{title} · Sticky Note · Vantage")
            self.editor.set_reference_entries(self.owner.note_editor._entries)
        finally:
            self._loading = False

    def _changed(self):
        if self._loading:
            return
        self.status.setText("Saving…")
        self.status.setAccessibleDescription("Sticky note changes are saving")
        self._save_timer.start()

    def _save(self):
        if self._loading or not self.note_id:
            return
        error = self.owner._save_from_sticky(
            self.note_id, self.title.text(), self.editor.toPlainText())
        message = error or "Saved"
        self.status.setText(message)
        self.status.setAccessibleDescription(message)
        if error:
            event = QAccessibleAnnouncementEvent(self.status, message)
            event.setPoliteness(QAccessible.AnnouncementPoliteness.Assertive)
            QAccessible.updateAccessibility(event)
        if not error:
            self.setWindowTitle(
                f"{self.title.text().strip() or 'Untitled note'} · Sticky Note · Vantage")

    def _open_in_notes(self):
        self._save_timer.stop()
        self._save()
        self.owner._open_note_from_sticky(self.note_id)

    def _return_to_notes(self):
        self._save_timer.stop()
        self._save()
        self.owner._set_note_sticky(self.note_id, False)
        self._return_focus_to_owner()

    def _return_focus_to_owner(self):
        if not self.owner.isVisible():
            return
        owner = self.owner

        def restore_focus():
            if not owner.isVisible():
                return
            owner.raise_()
            owner.activateWindow()
            QApplication.setActiveWindow(owner)
            owner._surface.setFocusProxy(owner.sticky_note_button)
            owner._scale_view.setFocus(Qt.FocusReason.OtherFocusReason)
            owner._scale_scene.setFocus(Qt.FocusReason.OtherFocusReason)
            owner._scale_proxy.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            owner._scale_scene.setActivePanel(owner._scale_proxy)
            owner._scale_scene.setFocusItem(
                owner._scale_proxy, Qt.FocusReason.OtherFocusReason)
            owner._scale_proxy.setFocus(Qt.FocusReason.OtherFocusReason)
            owner._surface.setFocus(Qt.FocusReason.OtherFocusReason)
            owner.sticky_note_button.setFocus(Qt.FocusReason.OtherFocusReason)

        # The native close event clears focus after its handler returns, so the
        # hand-off must run on the following event-loop turn.
        QTimer.singleShot(10, owner, restore_focus)

    def _geometry(self):
        return [self.x(), self.y(), self.width(), self.height()]

    def _save_geometry(self):
        if not self._quitting and self.note_id:
            self.owner._save_sticky_geometry(self.note_id, self._geometry())

    def _prepare_to_quit(self):
        self._quitting = True
        self._save_timer.stop()
        self._save()
        if self.note_id:
            self.owner._save_sticky_geometry(self.note_id, self._geometry())

    def dismiss(self):
        self._quitting = True
        self._save_timer.stop()
        self.hide()
        self.deleteLater()

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "_geometry_timer"):
            self._geometry_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_geometry_timer"):
            self._geometry_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.owner._update_sticky_action()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.owner._update_sticky_action()

    def closeEvent(self, event):
        self._save_timer.stop()
        self._save()
        if self._quitting:
            event.accept()
            return
        self._save_geometry()
        self.hide()
        self.owner._update_sticky_action()
        self._return_focus_to_owner()
        event.ignore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
            return
        super().keyPressEvent(event)


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
        self._sticky_windows = {}
        self._journal_stamp = self._journal_file_stamp()
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
        QTimer.singleShot(0, self._sync_sticky_windows)

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
            "That one P99 dump includes carried and bank items. Find dumps scans "
            "the complete configured EverQuest folder and only reads valid dumps.")
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
        self.import_button = QPushButton("Find dumps")
        self.import_button.setIcon(game_icon("import"))
        self.import_button.setAccessibleName(
            "Find P99 inventory dumps in the EverQuest folder")
        self.import_button.setToolTip(
            "Search the complete EverQuest folder for Location, Name, ID, Count, Slots dumps")
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
        self.sticky_note_button = QPushButton("Make sticky")
        self.sticky_note_button.setIcon(game_icon("ph-backpack"))
        self.sticky_note_button.setAccessibleName(
            "Show the selected note as a floating sticky note")
        self.sticky_note_button.setToolTip(
            "Turn this saved note into a small always-on-top window; it remains "
            "the same synced note")
        self.sticky_note_button.clicked.connect(self._toggle_sticky_note)
        toolbar_layout.addWidget(self.sticky_note_button)
        self.delete_note_button = QPushButton("Delete note")
        self.delete_note_button.setIcon(game_icon("delete"))
        self.delete_note_button.clicked.connect(self._delete_note)
        toolbar_layout.addWidget(self.delete_note_button)
        self.note_status = QLabel(
            "Type @ to link content · Make sticky opens the same synced note")
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
        for window in self._sticky_windows.values():
            window.editor.set_reference_entries(self.note_editor._entries)

    def set_quest_catalog(self, names):
        existing = list(self.note_editor._entries)
        existing.extend(f"Quest · {name}" for name in names if str(name).strip())
        self.note_editor.set_reference_entries(existing)

    def _sync_quest_references(self):
        if self._quests._catalog:
            self._refresh_references()
            self._quest_catalog_timer.stop()

    def _import_dump(self):
        roots = self._dump_roots()
        if not roots:
            QMessageBox.information(
                self, "EverQuest folder needed",
                "Set your EverQuest folder in VantageUI or select the Logs "
                "folder from the Quick Bar. Vantage will then search that "
                "entire EverQuest folder automatically.")
            return
        discovered = {}
        for root in roots:
            for record in discover_inventory_dumps(root):
                discovered.setdefault(record["path"].casefold(), record)
        dumps = sorted(
            discovered.values(),
            key=lambda value: (
                -value["modified"], value["relative"].casefold()))
        if not dumps:
            self.item_status.setText(
                f"No inventory dumps found under {roots[0]}")
            QMessageBox.information(
                self, "No inventory dumps found",
                "Vantage searched the complete EverQuest folder and its "
                "subfolders. In game, run /outputfile inventory "
                "Character-Inventory.txt, then choose Find dumps again.")
            return
        labels = []
        lookup = {}
        for record in dumps:
            when = datetime.fromtimestamp(record["modified"]).strftime(
                "%Y-%m-%d %H:%M")
            label = (
                f"{record['character']}  ·  {when}  ·  "
                f"{record['relative']}")
            labels.append(label)
            lookup[label] = record["path"]
        selected, accepted = QInputDialog.getItem(
            self, "Choose inventory dump",
            f"Found {len(labels)} valid dump(s) in the EverQuest folder:",
            labels, 0, False)
        if not accepted or not selected:
            return
        self._import_dump_path(lookup[selected])

    def _dump_roots(self):
        """Resolve configured EQ roots without asking for individual files."""
        candidates = [config.data.get("vantage_ui", {}).get("eq_dir", "")]
        logs_root = everquest_root_from_logs(
            config.data.get("general", {}).get("eq_log_dir", ""))
        if logs_root is not None:
            candidates.append(str(logs_root))
        roots = []
        seen = set()
        for candidate in candidates:
            try:
                root = Path(candidate).expanduser().resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            key = str(root).casefold()
            if not root.is_dir() or key in seen:
                continue
            seen.add(key)
            roots.append(root)
        return roots

    def _import_dump_path(self, path):
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
        self._remember_journal_stamp()
        self._refresh_everything()
        index = self.character_selector.findData(snapshot["character"])
        self.character_selector.setCurrentIndex(max(0, index))
        self.item_status.setText(
            f"Imported {len(snapshot['items']):,} rows from {snapshot['source']}")
        return True

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
            self._remember_journal_stamp()
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
            self._remember_journal_stamp()
            self._refresh_items()

    def _restore_previous(self):
        character = self.character_selector.currentData() or ""
        if character and self._journal.restore_previous_import(character):
            self._remember_journal_stamp()
            self._refresh_everything()
            self.item_status.setText(f"Restored the prior import for {character}")

    def _undo(self):
        if self._journal.undo():
            self._remember_journal_stamp()
            self._refresh_everything()
            self._sync_sticky_windows()
            self.item_status.setText("Last local change undone")

    def _journal_file_stamp(self):
        try:
            details = self._journal.path.stat()
            return details.st_mtime_ns, details.st_size
        except OSError:
            return 0, 0

    def _remember_journal_stamp(self):
        self._journal_stamp = self._journal_file_stamp()

    def refresh_synced_content(self):
        """Reload an atomically received Device Sync journal without stale UI."""
        stamp = self._journal_file_stamp()
        if not stamp[0] or stamp == self._journal_stamp:
            return False
        if self._note_save_timer.isActive():
            QTimer.singleShot(700, self.refresh_synced_content)
            return False
        selected = self._current_note_id
        self._journal.load()
        self._journal_stamp = stamp
        self._refresh_everything()
        self._load_note_fields(selected)
        self._sync_sticky_windows()
        self.note_status.setText("Notes synced from another PC")
        self.note_status.setAccessibleDescription(
            "The saved notes were refreshed from Device Sync")
        return True

    def _load_note_fields(self, note_id):
        note = self._journal.note(note_id)
        self._loading_note = True
        try:
            self._current_note_id = str(note_id or "") if note else ""
            self.note_title.setText(note.get("title", "") if note else "")
            self.note_editor.setPlainText(note.get("text", "") if note else "")
            self._render_preview()
        finally:
            self._loading_note = False
        self.delete_note_button.setEnabled(bool(note))
        self._update_sticky_action()

    def _sticky_list_text(self, note):
        title = note.get("title") or "Untitled note"
        return f"Sticky · {title}" if note.get("sticky", False) else title

    def _refresh_notes(self):
        selected = self._current_note_id
        with QSignalBlocker(self.note_list):
            self.note_list.clear()
            for note in self._journal.data["notes"]:
                item = QListWidgetItem(self._sticky_list_text(note))
                item.setData(Qt.ItemDataRole.UserRole, note.get("id"))
                state = "Floating sticky · " if note.get("sticky", False) else ""
                item.setToolTip(
                    f"{state}Last saved {note.get('updated_at', '')}")
                self.note_list.addItem(item)
            match = next((index for index in range(self.note_list.count())
                          if self.note_list.item(index).data(
                              Qt.ItemDataRole.UserRole) == selected), -1)
            if match >= 0:
                self.note_list.setCurrentRow(match)
        self.delete_note_button.setEnabled(bool(self._current_note_id))
        self._update_sticky_action()

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
        self._remember_journal_stamp()
        self._update_sticky_action()

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
        self._load_note_fields(note_id)

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
            self._remember_journal_stamp()
            self.note_status.setText("Saving…")
            self._note_save_timer.start()
            return
        self.note_status.setText("Saving…")
        self._note_save_timer.start()

    def _save_current_note(self):
        if not self._current_note_id or self._loading_note:
            return
        self._note_save_timer.stop()
        try:
            self._journal.upsert_note(
                self._current_note_id, self.note_title.text(),
                self.note_editor.toPlainText())
        except ValueError as error:
            self.note_status.setText(str(error))
            return
        self.note_status.setText("Saved locally")
        self._remember_journal_stamp()
        current = self.note_list.currentItem()
        if current:
            note = self._journal.note(self._current_note_id) or {}
            current.setText(self._sticky_list_text(note))
        self._render_preview()
        self._sync_one_sticky(self._current_note_id)

    def _delete_note(self):
        if not self._current_note_id:
            return
        if QMessageBox.question(
                self, "Delete note",
                "Delete this note? You can use Undo immediately afterward.") != \
                QMessageBox.StandardButton.Yes:
            return
        self._note_save_timer.stop()
        deleted_id = self._current_note_id
        self._journal.delete_note(deleted_id)
        self._remember_journal_stamp()
        self._remove_sticky_window(deleted_id)
        self._current_note_id = ""
        self._refresh_notes()
        self._loading_note = True
        self.note_title.clear()
        self.note_editor.clear()
        self.note_preview.clear()
        self._loading_note = False
        self._update_sticky_action()

    def _update_sticky_action(self):
        if not hasattr(self, "sticky_note_button"):
            return
        note = self._journal.note(self._current_note_id)
        self.sticky_note_button.setEnabled(bool(note))
        if not note:
            text = "Make sticky"
            accessible = "Select a note before making a floating sticky note"
        elif not note.get("sticky", False):
            text = "Make sticky"
            accessible = "Show the selected note as a floating sticky note"
        else:
            window = self._sticky_windows.get(self._current_note_id)
            visible = bool(window and window.isVisible())
            text = "Hide sticky" if visible else "Show sticky"
            accessible = (
                "Temporarily hide the selected floating sticky note"
                if visible else "Show the selected floating sticky note")
        self.sticky_note_button.setText(text)
        self.sticky_note_button.setAccessibleName(accessible)

    def _toggle_sticky_note(self):
        self._save_current_note()
        note = self._journal.note(self._current_note_id)
        if not note:
            return
        if not note.get("sticky", False):
            self._set_note_sticky(self._current_note_id, True)
            window = self._sticky_windows.get(self._current_note_id)
            if window:
                window.show()
                window.raise_()
                window.activateWindow()
                window.editor.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        window = self._sticky_windows.get(self._current_note_id)
        if window is None:
            self._sync_sticky_windows()
            window = self._sticky_windows.get(self._current_note_id)
        if not window:
            return
        if window.isVisible():
            window.close()
        else:
            window.show()
            window.raise_()
            window.activateWindow()
            window.editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._update_sticky_action()

    def _set_note_sticky(self, note_id, sticky):
        window = self._sticky_windows.get(note_id)
        geometry = window._geometry() if window else None
        if not self._journal.set_note_sticky(note_id, sticky, geometry):
            return False
        self._remember_journal_stamp()
        if not sticky:
            self._remove_sticky_window(note_id)
            self.note_status.setText("Returned to Notes · content kept")
        else:
            self._sync_sticky_windows()
            self.note_status.setText("Floating sticky created")
        self._refresh_notes()
        self._select_note_id(note_id)
        self._update_sticky_action()
        return True

    def _sync_sticky_windows(self):
        sticky_notes = {
            note.get("id"): note for note in self._journal.data["notes"]
            if note.get("id") and note.get("sticky", False)}
        for note_id in list(self._sticky_windows):
            if note_id not in sticky_notes:
                self._remove_sticky_window(note_id)
        for note_id, note in sticky_notes.items():
            window = self._sticky_windows.get(note_id)
            if window is None:
                window = StickyNoteWindow(self, note)
                self._sticky_windows[note_id] = window
                window.show()
            else:
                window.apply_note(note)
            window.editor.set_reference_entries(self.note_editor._entries)
        self._update_sticky_action()

    def _sync_one_sticky(self, note_id):
        note = self._journal.note(note_id)
        window = self._sticky_windows.get(note_id)
        if note and note.get("sticky", False):
            if window is None:
                self._sync_sticky_windows()
            else:
                window.apply_note(note)
        elif window is not None:
            self._remove_sticky_window(note_id)
        self._update_sticky_action()

    def _remove_sticky_window(self, note_id):
        window = self._sticky_windows.pop(str(note_id or ""), None)
        if window:
            window.dismiss()

    def _save_from_sticky(self, note_id, title, text):
        try:
            self._journal.upsert_note(note_id, title, text)
        except ValueError as error:
            return str(error)
        self._remember_journal_stamp()
        note = self._journal.note(note_id) or {}
        if self._current_note_id == note_id:
            self._loading_note = True
            try:
                if self.note_title.text() != title:
                    self.note_title.setText(title)
                if self.note_editor.toPlainText() != text:
                    self.note_editor.setPlainText(text)
                self._render_preview()
            finally:
                self._loading_note = False
        for index in range(self.note_list.count()):
            item = self.note_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == note_id:
                item.setText(self._sticky_list_text(note))
                break
        self.note_status.setText("Saved from floating sticky")
        return ""

    def _save_sticky_geometry(self, note_id, geometry):
        if self._journal.set_note_geometry(note_id, geometry):
            self._remember_journal_stamp()

    def _open_note_from_sticky(self, note_id):
        if not self.isVisible():
            self.toggle()
        self.raise_()
        self.activateWindow()
        self.tabs.setCurrentIndex(1)
        self._select_note_id(note_id)
        self._load_note_fields(note_id)
        self.note_title.setFocus(Qt.FocusReason.OtherFocusReason)

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
