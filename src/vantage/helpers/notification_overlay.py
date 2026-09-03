"""Movable, stacked, click-through notification surfaces.

Overlays are user-defined surfaces, not hard-coded alert windows.  The model
mirrors the useful behavior of dedicated EQ trigger tools while keeping all
rendering and configuration native to Vantage.
"""

from copy import deepcopy
import time

from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QProgressBar,
    QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from vantage.helpers import config


POSITIONS = (
    ("Top left", "top_left"), ("Top center", "top_center"),
    ("Top right", "top_right"),
    ("Middle left", "middle_left"), ("Middle center", "middle_center"),
    ("Middle right", "middle_right"),
    ("Bottom left", "bottom_left"), ("Bottom center", "bottom_center"),
    ("Bottom right", "bottom_right"),
)
OVERLAY_TYPES = (("Text overlay", "text"), ("Timer overlay", "timer"))
FONT_WEIGHTS = (
    ("Regular", "normal"), ("Medium", "medium"), ("Bold", "bold"))


class OverlayResizeHandle(QWidget):
    """Invisible GINA-style resize edge shown only while arranging."""

    CURSORS = {
        "top": Qt.CursorShape.SizeVerCursor,
        "bottom": Qt.CursorShape.SizeVerCursor,
        "left": Qt.CursorShape.SizeHorCursor,
        "right": Qt.CursorShape.SizeHorCursor,
        "top_left": Qt.CursorShape.SizeFDiagCursor,
        "bottom_right": Qt.CursorShape.SizeFDiagCursor,
        "top_right": Qt.CursorShape.SizeBDiagCursor,
        "bottom_left": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self, direction, overlay):
        super().__init__(overlay)
        self.direction = direction
        self.overlay = overlay
        label = direction.replace("_", " ")
        self.setObjectName(f"NotificationOverlayResize_{direction}")
        self.setCursor(self.CURSORS[direction])
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(f"Resize overlay from {label}")
        self.setToolTip(f"Drag the {label} edge to resize this overlay")

    def mousePressEvent(self, event):
        if (self.overlay._editing and
                event.button() == Qt.MouseButton.LeftButton):
            self.overlay._start_resize(
                self.direction, event.globalPosition().toPoint())
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.overlay._editing and
                event.buttons() & Qt.MouseButton.LeftButton):
            self.overlay._drag_resize(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.mouseGrabber() is self:
                self.releaseMouse()
            self.overlay._stop_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)


def reroute_overlay_references(deleted_ids, definitions):
    """Move every saved route away from overlays that no longer exist."""
    deleted = {str(value) for value in deleted_ids or ()}
    if not deleted:
        return
    def fallback(overlay_type):
        candidates = [
            overlay_id for overlay_id, settings in definitions.items()
            if settings.get("type", "text") == overlay_type]
        enabled = [
            overlay_id for overlay_id in candidates
            if definitions[overlay_id].get("enabled", True)]
        return next(iter(enabled or candidates or definitions), "")

    for item in config.data.get("spells", {}).get("custom_timers", []):
        if len(item) <= 10 or item[10] not in deleted:
            continue
        timer_type = str(item[15] if len(item) > 15 else "auto")
        is_timer = (
            timer_type in {"countdown", "stopwatch", "repeating"} or
            (timer_type == "auto" and str(item[2]) != "00:00:00"))
        item[10] = fallback("timer" if is_timer else "text")

    combat = config.data.get("combat", {})
    for key in (
            "live_overlay_id", "secondary_overlay_id",
            "tanking_overlay_id"):
        if combat.get(key) in deleted:
            combat[key] = fallback("text")


def _rgba(hex_color, opacity):
    color = str(hex_color or "#0B0D10").strip().lstrip("#")
    if len(color) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in color):
        color = "0B0D10"
    red, green, blue = (
        int(color[index:index + 2], 16) for index in (0, 2, 4))
    alpha = round(255 * max(0, min(100, int(opacity))) / 100)
    return f"rgba({red}, {green}, {blue}, {alpha})"


class OverlayMessageRow(QFrame):
    def __init__(self, entry, settings, progress_duration=None, parent=None):
        super().__init__(parent)
        self.setObjectName("NotificationOverlayRow")
        # Keep each notification at its natural content height.  Without this,
        # QVBoxLayout distributes a tall overlay's spare height across all rows,
        # which looks like large blank gaps between otherwise compact lines.
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        headline = QHBoxLayout()
        headline.setContentsMargins(0, 0, 0, 0)
        headline.setSpacing(3)
        self.title = QLabel(str(entry.get("title") or "Vantage"))
        self.title.setObjectName("NotificationOverlayTitle")
        headline.addWidget(self.title, 1)
        self.remaining = QLabel()
        self.remaining.setObjectName("NotificationOverlayRemaining")
        headline.addWidget(self.remaining)
        layout.addLayout(headline)
        self.message = QLabel(str(entry.get("message") or ""))
        self.message.setObjectName("NotificationOverlayMessage")
        self.message.setWordWrap(True)
        self.message.setVisible(bool(self.message.text().strip()))
        font_size = max(7, min(32, int(settings.get("font_size", 10))))
        font_weight = {
            "normal": QFont.Weight.Normal,
            "medium": QFont.Weight.Medium,
            "bold": QFont.Weight.Bold,
        }.get(settings.get("font_weight"), QFont.Weight.Medium)
        font_name = str(settings.get("font_name") or "Noto Sans")
        for label in (self.title, self.message, self.remaining):
            font = label.font()
            font.setPointSize(font_size)
            font.setFamily(font_name)
            font.setWeight(font_weight)
            label.setFont(font)
            text_color = str(entry.get("text_color") or "").strip()
            if text_color:
                label.setStyleSheet(f"color: {text_color};")
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setObjectName("NotificationOverlayProgress")
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar#NotificationOverlayProgress {"
            f"background: {settings.get('empty_bar_color', '#171B20')};"
            "border: 0; border-radius: 2px; min-height: 3px; max-height: 3px;}"
            "QProgressBar#NotificationOverlayProgress::chunk {"
            f"background: {entry.get('color') or settings.get('timer_bar_color', '#B5782F')};"
            "border-radius: 2px;}")
        layout.addWidget(self.progress)
        self._show_timer_bar = bool(settings.get("show_timer_bar", True))
        self.update_entry(entry, progress_duration)

    def update_entry(self, entry, progress_duration=None):
        duration = float(entry.get("duration") or 0)
        if entry.get("timer_mode") == "stopwatch":
            seconds = max(0, int(time.monotonic() - entry["started"]))
            minutes, seconds_part = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            self.remaining.setText(
                f"{hours}:{minutes:02d}:{seconds_part:02d}" if hours else
                f"{minutes}:{seconds_part:02d}")
            self.remaining.show()
            self.progress.hide()
            return
        if duration <= 0:
            self.remaining.hide()
            self.progress.hide()
            return
        seconds = max(0, int(entry["expires"] - time.monotonic() + 0.999))
        minutes, seconds_part = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        self.remaining.setText(
            f"{hours}:{minutes:02d}:{seconds_part:02d}" if hours else
            f"{minutes}:{seconds_part:02d}")
        elapsed = max(0.0, time.monotonic() - entry["started"])
        bar_duration = max(duration, float(progress_duration or duration))
        self.progress.setValue(max(0, min(
            1000, round(max(0.0, duration - elapsed) / bar_duration * 1000))))
        self.remaining.show()
        self.progress.setVisible(self._show_timer_bar)


class NotificationOverlay(QWidget):
    """One independently arranged overlay with a bounded message stack."""

    deleteRequested = Signal(str)

    def __init__(self, overlay_id, label, default_position):
        super().__init__()
        self.overlay_id = overlay_id
        self.label = label
        self.default_position = default_position
        self._editing = False
        self._drag_offset = None
        self._resize_state = None
        self._edit_snapshot = None
        self._edit_geometry = None
        self._entries = []
        self._rows = []
        self._section_headers = []
        # Compatibility aliases used by previews and lightweight tests.
        self.title = QLabel()
        self.message = QLabel()
        self.setObjectName("NotificationOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # The runtime surface can be genuinely small. Arrangement controls are
        # temporary and may clip at extreme sizes, just as GINA's ghost window
        # does, but the saved notification geometry is never inflated.
        self.setMinimumSize(96, 32)
        self.resize(320, 150)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("NotificationOverlayCard")
        self._card_layout = QVBoxLayout(self.card)
        self._card_layout.setContentsMargins(6, 3, 6, 4)
        self._card_layout.setSpacing(0)

        self._edit_bar = QWidget()
        self._edit_bar.setObjectName("NotificationOverlayEditBar")
        edit_layout = QHBoxLayout(self._edit_bar)
        edit_layout.setContentsMargins(0, 0, 0, 2)
        edit_layout.setSpacing(3)
        self._edit_label = QLabel(f"{label.upper()} · DRAG TO MOVE")
        self._edit_label.setObjectName("NotificationOverlayEditLabel")
        self._edit_label.setToolTip("Drag this overlay anywhere on the screen")
        self._edit_label.mousePressEvent = self._start_drag
        self._edit_label.mouseMoveEvent = self._drag
        self._edit_label.mouseReleaseEvent = self._stop_drag
        edit_layout.addWidget(self._edit_label, 1)
        options = QPushButton("Properties")
        options.setObjectName("NotificationOverlayOption")
        options.setToolTip(
            "Edit ordering, grouping, timer bars, font, background, or delete this overlay")
        options.clicked.connect(self._show_options)
        edit_layout.addWidget(options)
        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setObjectName("NotificationOverlayCancel")
        self._cancel_button.setToolTip(
            "Discard position, size, and property changes made in this preview")
        self._cancel_button.clicked.connect(self.cancel_edit)
        edit_layout.addWidget(self._cancel_button)
        self._lock_button = QPushButton("Save")
        self._lock_button.setObjectName("NotificationOverlaySave")
        self._lock_button.setToolTip(
            "Save this overlay and return it to locked click-through mode")
        self._lock_button.clicked.connect(self.finish_edit)
        edit_layout.addWidget(self._lock_button)
        self._card_layout.addWidget(self._edit_bar)

        self._messages = QWidget()
        self._message_layout = QVBoxLayout(self._messages)
        self._message_layout.setContentsMargins(0, 0, 0, 0)
        self._message_layout.setSpacing(0)
        self._message_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._card_layout.addWidget(self._messages, 1)
        root.addWidget(self.card)

        self._resize_handles = {
            direction: OverlayResizeHandle(direction, self)
            for direction in OverlayResizeHandle.CURSORS
        }
        # Compatibility alias retained for older previews/tests; it now points
        # at the real lower-right edge handle instead of a one-corner grip.
        self._size_grip = self._resize_handles["bottom_right"]
        for handle in self._resize_handles.values():
            handle.hide()
        self._edit_bar.hide()

        self._expiry_timer = QTimer(self)
        self._expiry_timer.setInterval(500)
        self._expiry_timer.timeout.connect(self._expire_entries)
        self._apply_window_mode(False)
        self._restore_geometry()
        self._apply_appearance()

    def _settings(self):
        overlays = config.data.setdefault("general", {}).setdefault(
            "notification_overlays", {})
        settings = overlays.setdefault(
            self.overlay_id,
            config.notification_overlay_defaults(self.overlay_id))
        return settings

    def _restore_geometry(self):
        geometry = self._settings().get("geometry")
        if (isinstance(geometry, list) and len(geometry) == 4
                and geometry[2] >= 96 and geometry[3] >= 32):
            self.setGeometry(*[int(value) for value in geometry])
            self._keep_on_a_screen()
        else:
            self._place(self.default_position)

    def _save_geometry(self):
        rect = self.geometry()
        self._settings()["geometry"] = [
            rect.x(), rect.y(), rect.width(), rect.height()]
        config.save()

    def _apply_appearance(self, faded=False):
        settings = self._settings()
        color_key = "faded_background_color" if faded else "background_color"
        opacity_key = (
            "faded_background_opacity" if faded else "background_opacity")
        background = _rgba(
            settings.get(color_key),
            settings.get(opacity_key, 65 if faded else 92))
        font_color = str(settings.get("font_color") or "#F2EAD8")
        font_name = str(settings.get("font_name") or "Noto Sans").replace(
            '"', '')
        font_size = max(7, min(32, int(settings.get("font_size", 10))))
        font_weight = {
            "normal": 400, "medium": 500, "bold": 700,
        }.get(settings.get("font_weight"), 500)
        border = (
            "border: 1px solid #9A7B42;" if self._editing else
            "border: 1px solid rgba(91, 85, 72, 80);")
        self.card.setStyleSheet(
            "QFrame#NotificationOverlayCard {"
            f"background-color: {background};"
            f"{border}"
            "border-radius: 7px; }"
            "QLabel#NotificationOverlayTitle, "
            "QLabel#NotificationOverlayMessage, "
            "QLabel#NotificationOverlayRemaining {"
            f"color: {font_color}; font-family: \"{font_name}\"; "
            f"font-size: {font_size}pt; font-weight: {font_weight}; }}"
            "QLabel#NotificationOverlayCharacterHeader {"
            "color: #D8BF7D; background: transparent; "
            "border: none; border-bottom: 1px solid #4A4232; "
            "padding: 1px 0 0 0; font-size: 8pt; font-weight: 600; }")

    def _window_flags(self, editing):
        flags = (
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint)
        if not editing:
            flags |= (
                Qt.WindowType.WindowDoesNotAcceptFocus |
                Qt.WindowType.WindowTransparentForInput)
        return flags

    def _apply_window_mode(self, editing):
        geometry = self.geometry()
        visible = self.isVisible()
        self.setWindowFlags(self._window_flags(editing))
        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating, not editing)
        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus if editing else Qt.FocusPolicy.NoFocus)
        self.setGeometry(geometry)
        if visible:
            self.show()

    def begin_edit(self):
        if self._editing:
            self.show()
            self.raise_()
            return
        self._edit_snapshot = deepcopy(self._settings())
        rect = self.geometry()
        self._edit_geometry = [
            rect.x(), rect.y(), rect.width(), rect.height()]
        self._editing = True
        self._expiry_timer.stop()
        self._apply_window_mode(True)
        self._edit_bar.show()
        for handle in self._resize_handles.values():
            handle.show()
            handle.raise_()
        now = time.monotonic()
        self._entries = [
            {"title": f"Vantage · {self.label}",
             "message": "Drag the header. Resize from any edge or corner.",
             "started": now, "duration": 90,
             "expires": now + 90, "key": "preview-primary"},
            {"title": "Overlay preview",
             "message": "Properties are live here; Save locks it for play.",
             "started": now, "duration": 45,
             "expires": now + 45, "key": "preview-secondary"},
        ]
        self._render_entries()
        self._apply_appearance(False)
        for handle in self._resize_handles.values():
            handle.raise_()
        self.show()
        self.raise_()

    def finish_edit(self):
        if not self._editing:
            return
        self._save_geometry()
        self._editing = False
        self._edit_snapshot = None
        self._edit_geometry = None
        self._resize_state = None
        self._entries.clear()
        self._render_entries()
        self._edit_bar.hide()
        for handle in self._resize_handles.values():
            handle.hide()
        self._apply_window_mode(False)
        self._apply_appearance(False)
        self.hide()

    def cancel_edit(self):
        """Restore the exact pre-preview registry entry and geometry."""
        if not self._editing:
            return
        if self._edit_snapshot is not None:
            settings = self._settings()
            settings.clear()
            settings.update(deepcopy(self._edit_snapshot))
        if self._edit_geometry is not None:
            self.setGeometry(*self._edit_geometry)
        self._editing = False
        self._edit_snapshot = None
        self._edit_geometry = None
        self._resize_state = None
        self._entries.clear()
        self._render_entries()
        self._edit_bar.hide()
        for handle in self._resize_handles.values():
            handle.hide()
        self._apply_window_mode(False)
        self._apply_appearance(False)
        self.hide()

    def notify(
            self, title, message, msecs=None, position=None,
            countdown_seconds=0, timer_key=None, character="", color="",
            timer_mode="countdown", text_color=""):
        if self._editing:
            return False
        settings = self._settings()
        if not settings.get("enabled", True):
            return False
        title = str(title or "Vantage")
        countdown_seconds = max(0, int(countdown_seconds or 0))
        timer_mode = (
            timer_mode if timer_mode in ("countdown", "stopwatch")
            else "countdown")
        # A stable key may also replace a live text entry (for example the
        # combat DPS surface) without forcing a fake countdown onto it.
        key = (
            str(timer_key) if timer_key else
            str(title) if countdown_seconds or timer_mode == "stopwatch" else
            "")
        if key:
            self._entries = [
                entry for entry in self._entries if entry.get("key") != key]
        if settings.get("group_titles"):
            self._entries = [
                entry for entry in self._entries
                if not (
                    entry["title"].casefold() == title.casefold() and
                    (not settings.get("group_by_character") or
                     entry.get("character", "").casefold() ==
                     str(character or "").casefold()))]
        started = time.monotonic()
        if msecs is None:
            msecs = max(0, int(settings.get("text_fade_seconds", 8))) * 1000
        lifetime = (
            None if timer_mode == "stopwatch" else
            countdown_seconds if countdown_seconds else
            max(1.2, int(msecs) / 1000))
        self._entries.append({
            "title": title,
            "message": str(message or ""),
            "started": started,
            "duration": countdown_seconds,
            "timer_mode": timer_mode,
            "key": key,
            "character": str(character or ""),
            "color": str(color or ""),
            "text_color": str(text_color or ""),
            "lifetime": lifetime,
            "expires": None if lifetime is None else started + lifetime,
        })
        limit = max(1, min(20, int(settings.get("max_entries", 5))))
        self._entries = self._entries[-limit:]
        self._render_entries()
        self._apply_appearance(False)
        if position:
            self._place(position)
        elif not settings.get("geometry"):
            self._place(self.default_position)
        self.show()
        self.raise_()
        self._expiry_timer.start()
        return True

    def _render_entries(self):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        for header in self._section_headers:
            header.setParent(None)
            header.deleteLater()
        self._section_headers.clear()
        settings = self._settings()
        entries = self._sorted_entries()
        progress_duration = None
        if settings.get("standardize_timer_bars"):
            progress_duration = max(
                (float(entry.get("duration") or 0) for entry in entries),
                default=0)
        group_characters = bool(settings.get("group_by_character"))
        previous_character = None
        for entry in entries:
            character = str(entry.get("character") or "Shared")
            if group_characters and character.casefold() != previous_character:
                header = QLabel(character.upper(), self._messages)
                header.setObjectName("NotificationOverlayCharacterHeader")
                header.setAccessibleName(f"{character} timer group")
                header.setToolTip(
                    f"Timers triggered by the {character} log profile")
                self._message_layout.addWidget(header)
                self._section_headers.append(header)
                previous_character = character.casefold()
            row = OverlayMessageRow(
                entry, settings, progress_duration, self._messages)
            self._message_layout.addWidget(row)
            self._rows.append(row)
        if self._rows:
            self.title = self._rows[0].title
            self.message = self._rows[0].message
        else:
            self.title = QLabel()
            self.message = QLabel()

    def _sorted_entries(self):
        entries = list(self._entries)
        sort_method = self._settings().get("sort", "newest")
        if sort_method == "newest":
            entries.reverse()
        elif sort_method == "time_remaining":
            now = time.monotonic()
            entries.sort(key=lambda entry: (
                max(0, float(entry.get("expires") or now) - now)
                if entry.get("duration") else float("inf"),
                -float(entry.get("started") or 0)))
        elif sort_method == "oldest" or sort_method == "triggered":
            entries.sort(key=lambda entry: float(entry.get("started") or 0))
        if self._settings().get("group_by_character"):
            groups = {}
            for entry in entries:
                key = str(entry.get("character") or "Shared").casefold()
                groups.setdefault(key, []).append(entry)
            entries = [
                entry for grouped in groups.values() for entry in grouped]
        return entries

    def _expire_entries(self):
        if self._editing:
            return
        now = time.monotonic()
        remaining = [
            entry for entry in self._entries
            if entry["expires"] is None or entry["expires"] > now]
        if len(remaining) != len(self._entries):
            self._entries = remaining
            self._render_entries()
        else:
            settings = self._settings()
            display_entries = self._sorted_entries()
            progress_duration = None
            if settings.get("standardize_timer_bars"):
                progress_duration = max(
                    (float(entry.get("duration") or 0)
                     for entry in display_entries), default=0)
            for row, entry in zip(self._rows, display_entries):
                row.update_entry(entry, progress_duration)
        fading_entries = [
            entry for entry in self._entries
            if not entry.get("duration") and entry.get("expires") is not None]
        faded = bool(fading_entries) and all(
            entry["expires"] - now <= min(
                1.5, max(0.4, float(entry.get("lifetime") or 1) * 0.3))
            for entry in fading_entries)
        self._apply_appearance(faded)
        if not self._entries:
            self._expiry_timer.stop()
            self._apply_appearance(False)
            self.hide()

    def dismiss_timer(self, timer_key):
        key = str(timer_key or "")
        remaining = [
            entry for entry in self._entries if entry.get("key") != key]
        if len(remaining) != len(self._entries):
            self._entries = remaining
            self._render_entries()
        if not self._entries and not self._editing:
            self.hide()

    def _show_options(self):
        menu = QMenu(self)
        settings = self._settings()
        sort_menu = menu.addMenu("Sort")
        sort_actions = {}
        for label, value in (
                ("Newest first", "newest"),
                ("Oldest first", "oldest"),
                ("Least time remaining", "time_remaining")):
            item = sort_menu.addAction(label)
            item.setCheckable(True)
            item.setChecked(settings.get("sort", "newest") == value)
            sort_actions[item] = value
        grouped = menu.addAction("Group repeated titles")
        grouped.setCheckable(True)
        grouped.setChecked(bool(settings.get("group_titles", False)))
        group_characters = menu.addAction("Group rows by character")
        group_characters.setCheckable(True)
        group_characters.setChecked(bool(
            settings.get("group_by_character", False)))
        show_bars = menu.addAction("Show timer bars")
        show_bars.setCheckable(True)
        show_bars.setChecked(bool(settings.get("show_timer_bar", True)))
        show_bars.setEnabled(settings.get("type", "text") == "timer")
        standardize = menu.addAction("Standardize timer bar scale")
        standardize.setCheckable(True)
        standardize.setChecked(bool(
            settings.get("standardize_timer_bars", False)))
        standardize.setEnabled(settings.get("type", "text") == "timer")

        rows_menu = menu.addMenu("Visible messages")
        row_actions = {}
        for count in (1, 3, 5, 8):
            action = rows_menu.addAction(str(count))
            action.setCheckable(True)
            action.setChecked(settings.get("max_entries", 5) == count)
            row_actions[action] = count

        font_menu = menu.addMenu("Font size")
        font_actions = {}
        for size in (8, 10, 12, 14, 16):
            action = font_menu.addAction(f"{size} pt")
            action.setCheckable(True)
            action.setChecked(settings.get("font_size", 10) == size)
            font_actions[action] = size

        weight_menu = menu.addMenu("Font weight")
        weight_actions = {}
        for label, value in FONT_WEIGHTS:
            action = weight_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(settings.get("font_weight", "medium") == value)
            weight_actions[action] = value

        background_menu = menu.addMenu("Background")
        background_actions = {}
        for opacity in (40, 60, 75, 92, 100):
            action = background_menu.addAction(f"{opacity}%")
            action.setCheckable(True)
            action.setChecked(settings.get("background_opacity", 92) == opacity)
            background_actions[action] = opacity

        menu.addSeparator()
        delete_action = menu.addAction("Delete overlay…")
        delete_action.setEnabled(bool(
            config.data.get("general", {}).get(
                "notification_overlays", {})))

        action = menu.exec(self.mapToGlobal(self._lock_button.pos()))
        if action in sort_actions:
            settings["sort"] = sort_actions[action]
            settings["newest_first"] = settings["sort"] == "newest"
        elif action == grouped:
            settings["group_titles"] = grouped.isChecked()
        elif action == group_characters:
            settings["group_by_character"] = group_characters.isChecked()
        elif action == show_bars:
            settings["show_timer_bar"] = show_bars.isChecked()
        elif action == standardize:
            settings["standardize_timer_bars"] = standardize.isChecked()
        elif action in row_actions:
            settings["max_entries"] = row_actions[action]
        elif action in font_actions:
            settings["font_size"] = font_actions[action]
        elif action in weight_actions:
            settings["font_weight"] = weight_actions[action]
        elif action in background_actions:
            settings["background_opacity"] = background_actions[action]
        elif action == delete_action:
            self.deleteRequested.emit(self.overlay_id)
            return
        else:
            return
        self._apply_appearance()
        self._render_entries()
        for handle in self._resize_handles.values():
            handle.raise_()

    def _start_drag(self, event):
        if self._editing and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft())
            event.accept()

    def _drag(self, event):
        if (self._editing and self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def _stop_drag(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            self._keep_on_a_screen()
            event.accept()

    def _start_resize(self, direction, global_position):
        if not self._editing:
            return
        rect = self.geometry()
        self._resize_state = (
            str(direction), global_position,
            [rect.x(), rect.y(), rect.width(), rect.height()])

    def _drag_resize(self, global_position):
        if not self._editing or self._resize_state is None:
            return
        direction, origin, geometry = self._resize_state
        start_x, start_y, start_width, start_height = geometry
        delta = global_position - origin
        minimum_width = self.minimumWidth()
        minimum_height = self.minimumHeight()
        left = start_x
        top = start_y
        width = start_width
        height = start_height
        if "left" in direction:
            width = max(minimum_width, start_width - delta.x())
            left = start_x + start_width - width
        elif "right" in direction:
            width = max(minimum_width, start_width + delta.x())
        if "top" in direction:
            height = max(minimum_height, start_height - delta.y())
            top = start_y + start_height - height
        elif "bottom" in direction:
            height = max(minimum_height, start_height + delta.y())
        self.setGeometry(left, top, width, height)

    def _stop_resize(self):
        if self._resize_state is None:
            return
        self._resize_state = None
        self._keep_on_a_screen()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        thickness = 5
        corner = 11
        width = self.width()
        height = self.height()
        self._resize_handles["top"].setGeometry(
            corner, 0, max(1, width - 2 * corner), thickness)
        self._resize_handles["bottom"].setGeometry(
            corner, max(0, height - thickness),
            max(1, width - 2 * corner), thickness)
        self._resize_handles["left"].setGeometry(
            0, corner, thickness, max(1, height - 2 * corner))
        self._resize_handles["right"].setGeometry(
            max(0, width - thickness), corner, thickness,
            max(1, height - 2 * corner))
        self._resize_handles["top_left"].setGeometry(0, 0, corner, corner)
        self._resize_handles["top_right"].setGeometry(
            max(0, width - corner), 0, corner, corner)
        self._resize_handles["bottom_left"].setGeometry(
            0, max(0, height - corner), corner, corner)
        self._resize_handles["bottom_right"].setGeometry(
            max(0, width - corner), max(0, height - corner),
            corner, corner)
        if self._editing:
            for handle in self._resize_handles.values():
                handle.raise_()

    def _place(self, position):
        screen = QApplication.screenAt(self.cursor().pos()) \
            or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        margin = 18
        if position.endswith("left"):
            x = area.left() + margin
        elif position.endswith("center"):
            x = area.center().x() - self.width() // 2
        else:
            x = area.right() - self.width() - margin + 1
        if position.startswith("bottom"):
            y = area.bottom() - self.height() - margin + 1
        elif position.startswith("middle"):
            y = area.center().y() - self.height() // 2
        else:
            y = area.top() + margin
        self.move(x, y)

    def _keep_on_a_screen(self):
        screen = QApplication.screenAt(self.frameGeometry().center()) \
            or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        width = min(self.width(), area.width())
        height = min(self.height(), area.height())
        x = min(max(self.x(), area.left()), area.right() - width + 1)
        y = min(max(self.y(), area.top()), area.bottom() - height + 1)
        self.setGeometry(x, y, width, height)


class NotificationOverlayManager:
    def __init__(self):
        self.overlays = {}
        self.reload()

    def definitions(self):
        return config.data.setdefault("general", {}).setdefault(
            "notification_overlays", {})

    def reload(self):
        """Rebuild overlay windows from the saved registry."""
        for overlay in self.overlays.values():
            overlay.finish_edit()
            overlay.close()
            overlay.deleteLater()
        self.overlays = {}
        normalized = config.normalize_notification_overlays(
            self.definitions(), seed_defaults=False)
        config.data["general"]["notification_overlays"] = normalized
        for overlay_id, settings in normalized.items():
            overlay = NotificationOverlay(
                overlay_id,
                settings.get("label") or overlay_id.replace("_", " ").title(),
                settings.get("default_position", "top_center"))
            overlay.deleteRequested.connect(self._confirm_delete)
            self.overlays[overlay_id] = overlay

    def fallback_id(self, overlay_type=None):
        for overlay_id, settings in self.definitions().items():
            if (settings.get("enabled", True) and
                    (overlay_type is None or
                     settings.get("type", "text") == overlay_type)):
                return overlay_id
        return next(iter(self.overlays), "")

    def create_overlay(self, overlay_type="text", label=""):
        overlay_type = "timer" if overlay_type == "timer" else "text"
        overlays = self.definitions()
        index = 1
        prefix = "timer_overlay" if overlay_type == "timer" else "text_overlay"
        while f"{prefix}_{index}" in overlays:
            index += 1
        overlay_id = f"{prefix}_{index}"
        settings = config.notification_overlay_defaults(
            overlay_id, overlay_type)
        settings["label"] = str(label or settings["label"])
        overlays[overlay_id] = settings
        config.save()
        self.reload()
        return overlay_id

    def duplicate_overlay(self, overlay_id):
        source = self.definitions().get(overlay_id)
        if not source:
            return ""
        new_id = self.create_overlay(
            source.get("type", "text"),
            f"{source.get('label', 'Overlay')} copy")
        clone = dict(source)
        clone["label"] = f"{source.get('label', 'Overlay')} copy"
        clone.pop("geometry", None)
        self.definitions()[new_id] = clone
        config.save()
        self.reload()
        return new_id

    def delete_overlay(self, overlay_id):
        overlays = self.definitions()
        if overlay_id not in overlays:
            return False
        overlay = self.overlays.pop(overlay_id, None)
        if overlay:
            overlay.finish_edit()
            overlay.close()
            overlay.deleteLater()
        del overlays[overlay_id]
        reroute_overlay_references({overlay_id}, overlays)
        config.save()
        self.reload()
        return True

    def _confirm_delete(self, overlay_id):
        settings = self.definitions().get(overlay_id)
        if settings is None:
            return
        label = settings.get("label", overlay_id)
        detail = (
            " This is the last overlay, so on-screen notifications will be "
            "fully disabled until you create another one."
            if len(self.definitions()) == 1 else
            " Triggers routed here will be moved to another overlay.")
        answer = QMessageBox.question(
            self.overlays.get(overlay_id), "Delete overlay",
            f"Delete “{label}”?{detail}",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_overlay(overlay_id)

    def notify(
            self, title, message, msecs=None, position=None,
            overlay_id="alerts", countdown_seconds=0, timer_key=None,
            character="", color="", timer_mode="countdown",
            text_color=""):
        overlay = self.overlays.get(overlay_id)
        if overlay is None:
            overlay_type = (
                "timer" if countdown_seconds or timer_mode == "stopwatch"
                else "text")
            overlay = self.overlays.get(self.fallback_id(overlay_type))
        if overlay is None:
            return False
        return bool(overlay.notify(
            title, message, msecs=msecs, position=position,
            countdown_seconds=countdown_seconds, timer_key=timer_key,
            character=character, color=color, timer_mode=timer_mode,
            text_color=text_color))

    def dismiss_timer(self, timer_key):
        for overlay in self.overlays.values():
            overlay.dismiss_timer(timer_key)

    def edit(self, overlay_id):
        overlay = self.overlays.get(overlay_id)
        if overlay:
            overlay.begin_edit()

    def edit_all(self):
        for overlay in self.overlays.values():
            overlay.begin_edit()

    def close(self):
        for overlay in self.overlays.values():
            overlay.finish_edit()
            overlay.close()
