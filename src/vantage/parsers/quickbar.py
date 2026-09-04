"""Configurable always-on-top command bar for Vantage."""

from __future__ import annotations

from collections import deque
import time

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QFrame, QLabel, QProgressBar, QSizePolicy,
    QToolButton, QVBoxLayout)

from vantage.helpers import config
from vantage.helpers.audio import audio_muted
from vantage.helpers.icons import game_icon
from vantage.helpers.parser import ParserWindow
from vantage.helpers.quickbar_items import QUICKBAR_ITEMS


class QuickBarNotificationRail(QFrame):
    """Show one attributable event once, then clear it from the rail."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("QuickBarNotificationRail")
        self.setFixedHeight(19)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName("Quick Bar notification rail")
        self.setAccessibleDescription(
            "Shows the newest attributable Vantage event once")

        self._label = QLabel(self)
        self._label.setObjectName("QuickBarNotificationText")
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label.hide()
        self._notice_id = 0
        self._pending = deque(maxlen=20)
        self._moving = False
        self._reduce_motion = False

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(24)
        self._scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._scroll_timer.timeout.connect(self._advance)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(5000)
        self._clear_timer.timeout.connect(self._clear)

    def present(self, notice_id, text, reduce_motion=False, available=True):
        """Queue a notice for one complete marquee pass in arrival order."""
        try:
            notice_id = int(notice_id)
        except (TypeError, ValueError):
            return
        if notice_id <= self._notice_id or not str(text or "").strip():
            return
        self._notice_id = notice_id
        self._reduce_motion = bool(reduce_motion)
        clean = " ".join(str(text).split())
        # Hidden/vertical rails consume the event immediately. A notice is a
        # live event, not history that should surprise the user hours later.
        if not available or not self.isVisible():
            return
        self._pending.append(clean)
        if self._label.isVisible():
            self.setAccessibleDescription(
                f"{len(self._pending)} more notification" +
                ("s" if len(self._pending) != 1 else "") + " queued")
            return
        self._show_next()

    def _show_next(self):
        if not self._pending or not self.isVisible():
            self._clear_current()
            return
        clean = self._pending.popleft()
        self._scroll_timer.stop()
        self._clear_timer.stop()
        self._label.setText(clean)
        self._label.adjustSize()
        self._label.setFixedHeight(self.height() - 2)
        self._label.show()
        self.setToolTip(clean)
        self.setAccessibleName(f"Latest Vantage notification: {clean}")
        self.setAccessibleDescription(
            f"Marquee notification; {len(self._pending)} more queued")
        self._announce_accessibly(clean)
        if self._reduce_motion:
            self._moving = False
            # Preserve the meaningful type + source without moving or
            # squeezing a potentially unbounded message into this compact
            # surface. The complete notice remains in the accessible name.
            summary = " · ".join(clean.split(" · ")[:2])
            self._label.setText(summary)
            self._label.setFixedWidth(max(1, self.width() - 14))
            self._label.setGeometry(7, 1, self._label.width(), self.height() - 2)
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._clear_timer.start()
        else:
            self._moving = True
            self._label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._label.adjustSize()
            self._label.setFixedHeight(self.height() - 2)
            self._label.move(self.width() - 5, 1)
            if self.isVisible():
                self._scroll_timer.start()

    def _announce_accessibly(self, text):
        """Announce a newly accepted, visible event exactly once."""
        event = QAccessibleAnnouncementEvent(self, text)
        QAccessible.updateAccessibility(event)

    def set_motion_reduced(self, reduce_motion):
        reduce_motion = bool(reduce_motion)
        if reduce_motion == self._reduce_motion or not self._label.isVisible():
            self._reduce_motion = reduce_motion
            return
        self._reduce_motion = reduce_motion
        if reduce_motion:
            self._scroll_timer.stop()
            self._moving = False
            clean = self._label.text()
            self._label.setText(" · ".join(clean.split(" · ")[:2]))
            self._label.setFixedWidth(max(1, self.width() - 14))
            self._label.setGeometry(7, 1, self._label.width(), self.height() - 2)
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._clear_timer.start()

    def _advance(self):
        if not self.isVisible() or not self._label.isVisible():
            self._scroll_timer.stop()
            return
        self._label.move(self._label.x() - 2, 1)
        if self._label.x() + self._label.width() < 5:
            self._clear()

    def _clear(self):
        self._clear_current()
        if self._pending and self.isVisible():
            self._show_next()

    def _clear_current(self):
        self._scroll_timer.stop()
        self._clear_timer.stop()
        self._moving = False
        self._label.clear()
        self._label.hide()
        self.setToolTip(
            "The next attributable Vantage event appears here")
        self.setAccessibleName("Quick Bar notification rail; no active notice")
        self.setAccessibleDescription(
            f"{len(self._pending)} notifications waiting")

    def showEvent(self, event):
        super().showEvent(event)
        if self._moving and self._label.isVisible():
            self._scroll_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._scroll_timer.stop()


class QuickBar(ParserWindow):
    """One taskbar-free surface for window toggles and tray commands."""

    name = "quickbar"
    _allow_clickthrough = False
    _LOG_ONLINE_DEBOUNCE_MS = 2000
    _DIALOG_ACTIONS = {
        "spell_library": ("_spell_library_dialog", "show_spell_library"),
        "mobile": ("_mobile_dialog_instance", "show_mobile_share"),
        "settings": ("_settings_instance", "show_settings"),
        "about": ("_about_dialog_instance", "show_about"),
        "updates": ("_update_dialog_instance", "show_update_dialog"),
        "log_status": ("_log_monitor_dialog_instance", "show_log_profiles"),
        "log_profiles": ("_log_monitor_dialog_instance", "show_log_profiles"),
    }

    def __init__(self, application, window_targets):
        self._application = application
        self._window_targets = dict(window_targets)
        self._target_names = {
            target: name for name, target in self._window_targets.items()}
        self._dialog_targets = {}
        self._buttons = {}
        self._enabled_dots = {}
        self._orientation = "horizontal"
        self._header_visible = True
        self._tick_snapshot = None
        self._snapping_height = False
        self._last_orientation_toggle = 0.0
        self._log_online = False
        self._log_pulse_on = False
        super().__init__()
        # Qt normally suppresses tooltips while EverQuest owns focus. This
        # attribute keeps hover help available without activating Vantage.
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self._surface.setAttribute(
            Qt.WidgetAttribute.WA_AlwaysShowToolTips, True)
        self.setWindowTitle("Vantage Quick Bar")
        self._title.setText("Quick Bar")
        self._title.setToolTip("Drag the Quick Bar to any screen edge")
        self._menu.mousePressEvent = self._start_move
        self._refresh_title_icon()
        self._title_icon.setMinimumSize(18, 18)
        self._title_icon.setMaximumHeight(18)
        self._title_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_icon.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._setup_actions()
        # The logical buttons remain 27 px, while the inherited graphics view
        # scales their complete replica. Do not let QGraphicsView's scene size
        # hint become a large native minimum width.
        self._scale_view.setMinimumSize(0, 0)
        self._scale_view.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        for target in self._window_targets.values():
            target.installEventFilter(self)
        tick = self._window_targets.get("tick")
        if tick is not None and hasattr(tick, "tray_state_changed"):
            tick.tray_state_changed.connect(self._server_tick_update)
        # Rebuild the authored strip first, then derive its scale from the
        # saved physical width. Using the stale static design height here made
        # every restart shrink a customized Quick Bar a second time.
        self._apply_quickbar_settings(preserve_scale=False)
        self.refresh_state()

    def _setup_actions(self):
        self.action_frame = QFrame()
        self.action_frame.setObjectName("QuickBarActions")
        self.action_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.action_layout.setContentsMargins(3, 2, 3, 3)
        self.action_layout.setSpacing(1)

        self.orientation_button = QToolButton()
        self.orientation_button.setObjectName("QuickBarOrientationButton")
        self.orientation_button.setAutoRaise(True)
        self.orientation_button.setFixedSize(24, 24)
        self.orientation_button.setIconSize(QSize(15, 15))
        self.orientation_button.setAccessibleName(
            "Switch Quick Bar orientation")
        self.orientation_button.clicked.connect(self.toggle_orientation)
        self.action_layout.addWidget(self.orientation_button, 0)

        for key, label, icon_name, _group in QUICKBAR_ITEMS:
            button = QToolButton()
            button.setObjectName("QuickBarButton")
            button.setAutoRaise(True)
            button.setIcon(game_icon(icon_name))
            button.setFixedSize(24, 24)
            button.setIconSize(QSize(16, 16))
            button.setAccessibleName(label)
            button.setProperty("BaseLabel", label)
            button.setToolTip(label)
            button.setCheckable(
                key in self._window_targets or key in self._DIALOG_ACTIONS or
                key == "mute")
            if button.isCheckable():
                dot = QFrame(button)
                dot.setObjectName("QuickBarEnabledDot")
                dot.setFixedSize(6, 6)
                dot.move(16, 2)
                dot.setAttribute(
                    Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                dot.hide()
                self._enabled_dots[key] = dot
            button.clicked.connect(
                lambda _checked=False, item_key=key:
                self._trigger(item_key))
            self._buttons[key] = button
            self.action_layout.addWidget(button, 0)
            if key == "tick":
                self._setup_tick_readout()

        self._update_badge = QLabel("!", self._buttons["updates"])
        self._update_badge.setObjectName("QuickBarAlertBadge")
        self._update_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_badge.setGeometry(15, 1, 8, 9)
        self._update_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._update_badge.hide()

        support = self._buttons["support"]
        support.setProperty("Support", True)
        support.setStyle(support.style())
        support.setToolTip(
            "Like this project? Support it — Buy Me a Coffee")
        support.setAccessibleDescription(
            "Opens the Vantage support page in your default browser")
        self._support_motion_marker = QFrame(support)
        self._support_motion_marker.setObjectName("QuickBarSupportSpark")
        self._support_motion_marker.setFixedSize(5, 5)
        self._support_motion_marker.move(2, 2)
        self._support_motion_marker.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._support_motion_marker.hide()
        logs_button = self._buttons["log_status"]
        self._log_motion_marker = QFrame(logs_button)
        self._log_motion_marker.setObjectName("QuickBarOnlineSpark")
        self._log_motion_marker.setFixedSize(5, 5)
        self._log_motion_marker.move(2, 2)
        self._log_motion_marker.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._log_motion_marker.hide()
        # Alternate fixed-size vector artwork instead of resizing or applying
        # a graphics effect. Effects and animated icon geometry can disappear
        # inside QGraphicsProxyWidget on some Windows graphics drivers.
        self._support_pulse_on = False
        self._support_pulse_timer = QTimer(self)
        self._support_pulse_timer.setInterval(520)
        # Precise timers remain dependable while EverQuest/WinEQ owns focus;
        # two sub-second UI pulses are still negligible compared with parsing.
        self._support_pulse_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._support_pulse_timer.timeout.connect(
            self._advance_support_pulse)

        self._log_pulse_timer = QTimer(self)
        self._log_pulse_timer.setInterval(620)
        self._log_pulse_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._log_pulse_timer.timeout.connect(self._advance_log_pulse)
        self._log_online_debounce = QTimer(self)
        self._log_online_debounce.setSingleShot(True)
        self._log_online_debounce.setInterval(
            self._LOG_ONLINE_DEBOUNCE_MS)
        self._log_online_debounce.setTimerType(Qt.TimerType.PreciseTimer)
        self._log_online_debounce.timeout.connect(
            self._start_log_animation_if_stable)

        self.action_frame.setLayout(self.action_layout)
        self.content.addWidget(
            self.action_frame, 0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.notification_rail = QuickBarNotificationRail()
        self.notification_rail.setToolTip(
            "The next attributable Vantage event appears here")
        self.content.addWidget(
            self.notification_rail, 0,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

    def _setup_tick_readout(self):
        self.tick_readout = QFrame()
        self.tick_readout.setObjectName("QuickBarTick")
        self.tick_readout.setFixedSize(48, 24)
        tick_layout = QVBoxLayout(self.tick_readout)
        tick_layout.setContentsMargins(2, 1, 2, 1)
        tick_layout.setSpacing(1)

        self.tick_countdown = QToolButton()
        self.tick_countdown.setObjectName("QuickBarTickCountdown")
        self.tick_countdown.setAutoRaise(True)
        self.tick_countdown.setText("—")
        self.tick_countdown.setFixedSize(44, 17)
        self.tick_countdown.setAccessibleName("Live Server Tick countdown")
        self.tick_countdown.setToolTip(
            "Server Tick is not synchronized · click to open it")
        self.tick_countdown.clicked.connect(
            lambda _checked=False: self._trigger("tick"))
        tick_layout.addWidget(self.tick_countdown)

        self.tick_progress = QProgressBar()
        self.tick_progress.setObjectName("QuickBarTickProgress")
        self.tick_progress.setRange(0, 1000)
        self.tick_progress.setValue(0)
        self.tick_progress.setTextVisible(False)
        self.tick_progress.setFixedSize(44, 3)
        self.tick_progress.setAccessibleName("Live Server Tick progress")
        self.tick_progress.setToolTip(
            "Progress toward the next six-second Server Tick")
        tick_layout.addWidget(self.tick_progress)
        self.action_layout.addWidget(self.tick_readout, 0)

    def finish_startup(self, show_on_launch=True):
        """Always expose the compact launcher while other tools stay hidden."""
        self._compact_header_controls()
        self._set_scaled_minimum_size()
        self._fit_to_available_screen()
        self._update_uniform_scale()
        self._toggled = True
        self.show()

    def _effective_minimum_scale(self):
        # A one-row command strip can remain recoverable at 18 px high; using
        # the generic panel's 48 px floor would prevent a compact top bar.
        if self._orientation == "vertical":
            # The vertical bar becomes narrow by removing its empty lane, not
            # by shrinking the interactive controls below their authored size.
            return 1.0
        interactive_height = self._design_size.height()
        rail = getattr(self, "notification_rail", None)
        if rail is not None and rail.isVisible():
            interactive_height -= rail.height()
        return max(
            self._minimum_scale,
            72 / max(1, self._design_size.width()),
            18 / max(1, interactive_height))

    def _refresh_title_icon(self):
        title_icon = getattr(self, "_title_icon", None)
        application = QApplication.instance()
        if title_icon is None or application is None:
            return
        logo = application.windowIcon()
        if not logo.isNull():
            title_icon.setPixmap(logo.pixmap(
                QSize(18, 18), max(1.0, self.devicePixelRatioF())))

    def _update_uniform_scale(self):
        """Keep a command strip tight instead of creating an empty viewport."""
        if (not self._collapsed and not self._snapping_height
                and getattr(self, "_design_size", None)):
            # The Quick Bar is a shrink-wrapped launcher, not a content
            # window. Never magnify it beyond its authored one-row/one-column
            # size; an accidental drag or double-click must not leave a giant
            # empty strip over EverQuest.
            scale = min(1.0, max(
                self._effective_minimum_scale(),
                self.width() / max(1, self._design_size.width())))
            target_width = max(1, round(
                self._design_size.width() * scale))
            target_height = max(1, round(self._design_size.height() * scale))
            if (abs(self.width() - target_width) > 1 or
                    abs(self.height() - target_height) > 1):
                self._snapping_height = True
                self.resize(target_width, target_height)
                self._snapping_height = False
        super()._update_uniform_scale()

    def parse(self, _timestamp, _text):
        """The Quick Bar contains commands and does not parse log lines."""

    def eventFilter(self, watched, event):
        if ((watched in self._target_names or
             watched in self._dialog_targets) and
                event.type() in (QEvent.Type.Show, QEvent.Type.Hide)):
            QTimer.singleShot(0, self.refresh_state)
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_state()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_support_animation()
        self._sync_log_animation()

    def _parser_settings_config_update_watcher(self):
        super()._parser_settings_config_update_watcher()
        self._apply_quickbar_settings(preserve_scale=True)
        self.refresh_state()

    def toggle_orientation(self):
        # A rapid double-click delivers two clicked signals even though the
        # first one has already rebuilt and moved the entire bar. Treat that
        # gesture as one orientation change instead of letting the second
        # release act on the freshly rearranged surface.
        now = time.monotonic()
        interval = max(0.25, QApplication.doubleClickInterval() / 1000)
        if now - self._last_orientation_toggle < interval:
            return
        self._last_orientation_toggle = now
        orientation = (
            "vertical" if self._orientation == "horizontal" else
            "horizontal")
        config.data["quickbar"]["orientation"] = orientation
        config.save()
        self._apply_quickbar_settings(preserve_scale=True)

    def toggle_header(self, enabled=None):
        if enabled is None:
            enabled = not self._header_visible
        config.data["quickbar"]["show_header"] = bool(enabled)
        config.save()
        self._apply_quickbar_settings(preserve_scale=True)

    def _build_window_context_menu(self):
        menu, actions = super()._build_window_context_menu()
        menu.addSeparator()
        show_header = menu.addAction("Show Quick Bar Header")
        show_header.setCheckable(True)
        show_header.setChecked(self._header_visible)
        show_header.setToolTip(
            "Turn this off to leave only the command buttons")
        show_header.triggered.connect(self.toggle_header)
        actions["quickbar_header"] = show_header
        if not self._header_visible:
            actions["roll"].setVisible(False)
        return menu, actions

    def _apply_quickbar_settings(self, preserve_scale=True):
        settings = config.data["quickbar"]
        self._orientation = settings.get("orientation", "horizontal")
        vertical = self._orientation == "vertical"
        self._header_visible = bool(settings.get("show_header", True))
        self._menu.setVisible(self._header_visible)
        self._menu.setEnabled(self._header_visible)
        self._title.setText("Quick Bar")
        self._title.setVisible(not vertical)
        self._title_icon.setVisible(True)
        self._title_icon.setSizePolicy(
            QSizePolicy.Policy.Expanding if vertical else
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred)
        # The vertical header is a centered branded drag handle. Its frame,
        # roll-up and tray commands remain available from the context menu.
        self._button.setVisible(not vertical)
        self._parser_menu_area.setVisible(not vertical)
        # The vertical rail already has a dedicated Settings action. Keeping
        # the base header gear beside the centered V logo exceeds the genuine
        # 30 px column and clips both controls.
        self._settings_button.setVisible(not vertical)
        self._roll_button.setVisible(not vertical)
        self._minimize_button.setVisible(not vertical)
        header_margin = 3 if vertical else 5
        self._menu_content.setContentsMargins(
            header_margin, 0, header_margin, 0)
        direction = (
            QBoxLayout.Direction.TopToBottom if vertical else
            QBoxLayout.Direction.LeftToRight)
        self.action_layout.setDirection(direction)
        self.action_frame.setProperty("Orientation", self._orientation)
        self.action_frame.setProperty(
            "HeaderHidden", not self._header_visible)
        self.action_frame.setStyle(self.action_frame.style())
        tick_width = 24 if vertical else 48
        tick_inner_width = 20 if vertical else 44
        self.tick_readout.setFixedSize(tick_width, 24)
        self.tick_countdown.setFixedSize(tick_inner_width, 17)
        self.tick_progress.setFixedSize(tick_inner_width, 3)
        self.tick_readout.setProperty("Compact", vertical)
        self.tick_readout.setStyle(self.tick_readout.style())
        self.orientation_button.setIcon(game_icon(
            "grid" if vertical else "layers"))
        self.orientation_button.setToolTip(
            "Switch to a horizontal Quick Bar" if vertical else
            "Switch to a vertical Quick Bar")

        visible_count = 1  # orientation button is deliberately permanent
        for key, button in self._buttons.items():
            visible = bool(settings.get(f"show_{key}", True))
            button.setVisible(visible)
            visible_count += int(visible)
        self._sync_support_animation()
        self._sync_log_animation()

        tick_visible = bool(settings.get("show_server_tick", True))
        self.tick_readout.setVisible(tick_visible)
        rail_visible = bool(
            settings.get("show_notification_ticker", True) and not vertical)
        self.notification_rail.setVisible(rail_visible)
        self.notification_rail.set_motion_reduced(
            config.data["general"].get("reduce_motion", False))
        item_count = visible_count + int(tick_visible)
        margins = self.action_layout.contentsMargins()
        spacing = self.action_layout.spacing()
        header_height = (
            self._menu.sizeHint().height() if self._header_visible else 0)
        header_width = (
            self._compact_header_width() if self._header_visible else 0)

        if vertical:
            self.content.setAlignment(
                self.action_frame,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            action_width = margins.left() + margins.right() + 24
            action_height = (
                margins.top() + margins.bottom() + visible_count * 24 +
                (24 if tick_visible else 0) +
                max(0, item_count - 1) * spacing)
            design_size = QSize(
                max(action_width, header_width),
                header_height + action_height)
        else:
            self.content.setAlignment(
                self.action_frame,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            action_width = (
                margins.left() + margins.right() + visible_count * 24 +
                (48 if tick_visible else 0) +
                max(0, item_count - 1) * spacing)
            action_height = margins.top() + margins.bottom() + 24
            rail_width = max(120, action_width - 24)
            self.notification_rail.setFixedWidth(rail_width)
            design_size = QSize(
                max(120, action_width, header_width),
                header_height + action_height +
                (self.notification_rail.height() if rail_visible else 0))
        self._set_design_size(design_size, preserve_scale=preserve_scale)
        self._update_uniform_scale()
        self._fit_to_available_screen()

    def _compact_header_width(self):
        """Let a vertical branded header fit the real one-column surface."""
        if self._orientation != "vertical":
            return super()._compact_header_width()
        margins = self._menu_content.contentsMargins()
        logo_width = max(
            self._title_icon.minimumSizeHint().width(),
            self._title_icon.sizeHint().width(), 18)
        return max(24, margins.left() + margins.right() + logo_width + 2)

    def _server_tick_update(self, snapshot, _compact=False):
        self._tick_snapshot = snapshot
        synced = bool(getattr(snapshot, "synced", False))
        pulse = bool(getattr(snapshot, "pulse", False)) and synced
        if not synced:
            text = "—"
            value = 0
            detail = "not synchronized"
        elif pulse:
            text = "TICK"
            value = 1000
            detail = "tick now"
        else:
            remaining = max(0.0, float(getattr(snapshot, "remaining", 0.0)))
            text = f"{remaining:.1f}"
            value = max(0, min(1000, round(
                float(getattr(snapshot, "progress", 0.0)) * 1000)))
            detail = f"{remaining:.1f} seconds remaining"
        self.tick_countdown.setText(text)
        self.tick_progress.setValue(value)
        self.tick_progress.setProperty("Pulse", pulse)
        self.tick_progress.setProperty("Synced", synced)
        self.tick_progress.setStyle(self.tick_progress.style())
        target = self._window_targets.get("tick")
        state = "open" if target is not None and target.isVisible() else "hidden"
        tooltip = f"Server Tick: {detail} · window is {state} · click to toggle"
        self.tick_countdown.setToolTip(tooltip)
        self.tick_progress.setToolTip(tooltip)
        self.tick_countdown.setAccessibleDescription(detail)

    def refresh_state(self):
        if not self._buttons:
            return
        for name, target in self._window_targets.items():
            button = self._buttons.get(name)
            if not button:
                continue
            visible = target.isVisible()
            button.blockSignals(True)
            button.setChecked(visible)
            button.blockSignals(False)
            dot = self._enabled_dots.get(name)
            if dot is not None:
                dot.setVisible(visible)
                dot.raise_()
            label = button.accessibleName()
            state = "open" if visible else "hidden"
            button.setToolTip(f"{label} is {state} · click to toggle")
            button.setAccessibleDescription(f"Currently {state}")

        for key, (attribute, _opener) in self._DIALOG_ACTIONS.items():
            button = self._buttons.get(key)
            if button is None:
                continue
            dialog = getattr(self._application, attribute, None)
            visible = bool(dialog is not None and dialog.isVisible())
            if dialog is not None and dialog not in self._dialog_targets:
                self._dialog_targets[dialog] = key
                dialog.installEventFilter(self)
            button.blockSignals(True)
            button.setChecked(visible)
            button.blockSignals(False)
            dot = self._enabled_dots.get(key)
            if dot is not None:
                dot.setVisible(visible)
                if visible:
                    dot.raise_()
            if key not in ("log_status", "log_profiles"):
                label = str(button.property("BaseLabel") or
                            button.accessibleName())
                state = "open" if visible else "hidden"
                button.setToolTip(f"{label} is {state} · click to toggle")
                button.setAccessibleDescription(f"Currently {state}")

        muted = audio_muted()
        mute_button = self._buttons["mute"]
        mute_button.blockSignals(True)
        mute_button.setChecked(muted)
        mute_button.blockSignals(False)
        mute_dot = self._enabled_dots.get("mute")
        if mute_dot is not None:
            mute_dot.setVisible(muted)
            mute_dot.raise_()
        blocked = str(getattr(
            self._application, "_last_audio_blocked", "None yet"))
        played = str(getattr(
            self._application, "_last_audio", "None yet"))
        mute_button.setToolTip(
            (("All Vantage audio is blocked · last played: " + played +
              " · last prevented: " + blocked)
             if muted else
             ("Mute all Vantage sounds · last played: " + played +
              " · last prevented: " + blocked)))
        mute_button.setAccessibleDescription(
            "All sounds are muted" if muted else "Sounds are active")

        status = str(getattr(
            self._application, "_log_status", "NO LOGS")).strip().upper()
        logs_button = self._buttons["log_status"]
        online = status == "ONLINE"
        self._log_online = online
        logs_button.setProperty("Status", status.casefold().replace(" ", "_"))
        logs_button.setProperty("LogOnline", online)
        display_status = (
            "DISCONNECTED" if status in {"NO LOGS", "DISCONNECTED"} else
            status)
        logs_button.setAccessibleName(f"Log Status: {display_status}")
        self._apply_log_status_copy(display_status)
        self._sync_log_animation()

        update_ready = self._application.new_version_available()
        update_button = self._buttons["updates"]
        update_state = str(getattr(
            self._application, "_update_check_state", "idle"))
        update_button.setProperty("Alert", update_ready)
        update_button.setProperty("UpdateState", update_state)
        update_button.setStyle(update_button.style())
        self._update_badge.setVisible(update_ready)
        if update_ready:
            self._update_badge.raise_()
        if update_ready:
            tooltip = "An update is ready · open the verified updater"
            accessible_name = "Update ready; open Vantage updater"
            description = "A verified Vantage update is ready to install"
        elif update_state == "checking":
            tooltip = "Checking GitHub for a verified Vantage update…"
            accessible_name = "Checking for Vantage updates"
            description = "The automatic update heartbeat is checking now"
        elif update_state == "retrying":
            tooltip = "Update check unavailable · retrying automatically"
            accessible_name = "Update check will retry automatically"
            description = "The update heartbeat will retry in about one minute"
        elif update_state == "disabled":
            tooltip = "Automatic update checks are off · click to check now"
            accessible_name = "Check manually for Vantage updates"
            description = "Automatic update heartbeat is disabled in Settings"
        else:
            tooltip = "Updates checked automatically every minute · click now"
            accessible_name = "Check for Vantage updates"
            description = "No verified update is currently waiting"
        update_button.setToolTip(tooltip)
        update_button.setAccessibleName(accessible_name)
        update_button.setAccessibleDescription(description)

        self._buttons["support"].setToolTip(
            "Like this project? Support it — Buy Me a Coffee")
        self._buttons["support"].setAccessibleDescription(
            "Opens the Vantage support page in your default browser")
        self._sync_support_animation()
        if self._tick_snapshot is not None:
            self._server_tick_update(self._tick_snapshot)
        notice_id = getattr(self._application, "_quickbar_notice_id", 0)
        notice = getattr(self._application, "_quickbar_notice", "")
        self.notification_rail.present(
            notice_id, notice,
            config.data["general"].get("reduce_motion", False),
            available=self.isVisible() and self.notification_rail.isVisible())

    def _sync_support_animation(self):
        support = self._buttons.get("support")
        if support is None or not hasattr(self, "_support_pulse_timer"):
            return
        enabled = bool(
            self.isVisible() and support.isVisible() and
            not config.data["general"].get("reduce_motion", False))
        if enabled:
            if not self._support_pulse_timer.isActive():
                self._support_pulse_on = True
                self._apply_support_pulse()
                self._support_pulse_timer.start()
        else:
            self._support_pulse_timer.stop()
            self._support_pulse_on = False
            self._apply_support_pulse()

    def _advance_support_pulse(self):
        if not self._support_animation_enabled():
            self._sync_support_animation()
            return
        self._support_pulse_on = not self._support_pulse_on
        self._apply_support_pulse()

    def _support_animation_enabled(self):
        support = self._buttons.get("support")
        return bool(
            support is not None and self.isVisible() and support.isVisible() and
            not config.data["general"].get("reduce_motion", False))

    def _apply_support_pulse(self):
        support = self._buttons.get("support")
        if support is None:
            return
        support.setProperty("Pulse", self._support_pulse_on)
        support.setIcon(game_icon(
            "ph-coffee-bright" if self._support_pulse_on else
            "ph-coffee-rest"))
        support.setIconSize(QSize(16, 16))
        self._support_motion_marker.setVisible(
            self._support_pulse_on and support.isVisible())
        self._repolish_animation_button(support)

    def _sync_log_animation(self):
        logs_button = self._buttons.get("log_status")
        if logs_button is None or not hasattr(self, "_log_pulse_timer"):
            return
        if self._log_animation_enabled():
            if (not self._log_pulse_timer.isActive() and
                    not self._log_online_debounce.isActive()):
                self._log_pulse_on = False
                self._apply_log_pulse()
                self._log_online_debounce.start()
        else:
            self._log_online_debounce.stop()
            self._log_pulse_timer.stop()
            self._log_pulse_on = False
            self._apply_log_pulse()
            if self._log_online:
                self._apply_log_status_copy("ONLINE")

    def _start_log_animation_if_stable(self):
        if not self._log_animation_enabled():
            self._sync_log_animation()
            return
        self._log_pulse_on = True
        self._apply_log_pulse()
        self._log_pulse_timer.start()
        self._apply_log_status_copy("ONLINE", stable=True)

    def _log_animation_enabled(self):
        logs_button = self._buttons.get("log_status")
        return bool(
            logs_button is not None and self._log_online and
            self.isVisible() and logs_button.isVisible() and
            not config.data["general"].get("reduce_motion", False))

    def _advance_log_pulse(self):
        if not self._log_animation_enabled():
            self._sync_log_animation()
            return
        self._log_pulse_on = not self._log_pulse_on
        self._apply_log_pulse()

    def _apply_log_pulse(self):
        logs_button = self._buttons.get("log_status")
        if logs_button is None:
            return
        logs_button.setProperty(
            "LivePulse", self._log_online and self._log_pulse_on)
        if self._log_online:
            icon_name = (
                "ph-pulse-online-bright" if self._log_pulse_on else
                "ph-pulse-online-rest")
        else:
            status = str(logs_button.property("Status") or "")
            icon_name = (
                "ph-pulse-quiet" if status in {"quiet", "waiting"} else
                "ph-pulse-disconnected" if status in {
                    "no_logs", "disconnected", "stale"} else
                "ph-pulse")
        logs_button.setIcon(game_icon(icon_name))
        logs_button.setIconSize(QSize(16, 16))
        self._log_motion_marker.setVisible(
            self._log_online and self._log_pulse_on and
            logs_button.isVisible())
        self._repolish_animation_button(logs_button)

    def _apply_log_status_copy(self, status, stable=False):
        logs_button = self._buttons.get("log_status")
        if logs_button is None:
            return
        if self._log_online:
            motion_off = config.data["general"].get(
                "reduce_motion", False)
            if stable:
                state = "stable live log activity detected"
            elif motion_off:
                state = "live log activity detected; animation is disabled"
            else:
                state = "live log activity detected; verifying stability"
            logs_button.setToolTip(
                f"Logs: ONLINE · {state} · "
                "click to inspect every log profile")
            logs_button.setAccessibleDescription(
                state.capitalize() + "; monitoring is ONLINE")
            return
        logs_button.setToolTip(
            f"Logs: {status} · click to inspect every log profile")
        logs_button.setAccessibleDescription(
            f"Log monitoring status is {status}")

    def _repolish_animation_button(self, button):
        """Refresh proxy-hosted button state without changing its geometry."""
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()
        self.action_frame.update()
        self._scale_proxy.update()
        self._scale_scene.update(self._scale_proxy.sceneBoundingRect())
        self._scale_view.viewport().update()

    def _trigger(self, key):
        if key in self._window_targets:
            target = self._window_targets[key]
            was_visible = target.isVisible()
            target.toggle()
            if was_visible and not target.isVisible():
                # The Quick Bar already owns the user's click. Returning Qt
                # focus within it does not activate the bar or pull foreground
                # focus away from EverQuest when invoked programmatically.
                button = self._buttons.get(key)
                if button is not None:
                    QTimer.singleShot(
                        0, lambda launcher=button: launcher.setFocus(
                            Qt.FocusReason.OtherFocusReason))
        elif key in self._DIALOG_ACTIONS:
            self._toggle_dialog_action(key)
        elif key == "support":
            self._application.show_support()
        elif key == "reload_ui":
            self._application.reload_ui()
        elif key == "link_logs":
            self._application.select_logs_folder()
        elif key == "log_help":
            self._application.show_log_help()
        elif key == "mute":
            self._application.toggle_audio_muted()
        elif key == "quit":
            self._application.quit_vantage(confirm=True, parent=self)
        QTimer.singleShot(0, self.refresh_state)

    def _toggle_dialog_action(self, key):
        """Give every Quick Bar window button true open/close behavior."""
        attribute, opener_name = self._DIALOG_ACTIONS[key]
        dialog = getattr(self._application, attribute, None)
        if dialog is not None and dialog.isVisible():
            dialog.close()
            return False
        opener = getattr(self._application, opener_name)
        if key == "settings":
            opener("Quick Bar")
        else:
            opener()
        dialog = getattr(self._application, attribute, None)
        if dialog is not None and dialog not in self._dialog_targets:
            self._dialog_targets[dialog] = key
            dialog.installEventFilter(self)
        return bool(dialog is not None and dialog.isVisible())
