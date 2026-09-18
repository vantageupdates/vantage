"""Configurable always-on-top command bar for Vantage."""

from __future__ import annotations

from collections import deque
import time

from PySide6.QtCore import (
    QEasingCurve, QEvent, QPointF, QPropertyAnimation, QSize, Qt, QTimer)
from PySide6.QtGui import (
    QAccessible, QAccessibleAnnouncementEvent, QColor, QPainter, QPen)
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QFrame, QGraphicsOpacityEffect, QLabel,
    QProgressBar, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget,
    QWidgetAction)

from vantage.helpers import config
from vantage.helpers.audio import (
    audio_muted, master_volume, set_master_volume)
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

        self._channel = QLabel("SYSTEM", self)
        self._channel.setObjectName("QuickBarNotificationChannel")
        self._channel.setFixedWidth(82)
        self._channel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._channel.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._channel.hide()
        self._label = QLabel(self)
        self._label.setObjectName("QuickBarNotificationText")
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label.hide()
        self._notice_id = 0
        self._pending = deque(maxlen=20)
        self._pending_channels = deque(maxlen=20)
        self._moving = False
        self._reduce_motion = False
        self._fade_on_expire = False

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._fade_animation = QPropertyAnimation(
            self._opacity_effect, b"opacity", self)
        self._fade_animation.setDuration(550)
        self._fade_animation.setStartValue(1.0)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.setEasingCurve(
            QEasingCurve.Type.InOutQuad)
        self._fade_animation.finished.connect(self._clear)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(24)
        self._scroll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._scroll_timer.timeout.connect(self._advance)
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.setInterval(5000)
        self._clear_timer.timeout.connect(self._expire_current)

    @staticmethod
    def _channel_label(channel):
        return {
            "spells": "BUFFS / SPELLS",
            "timers": "COMBAT / TIMERS",
            "market": "MARKET",
            "opendkp": "GUILD DKP",
            "quickbar": "CHAT",
            "chat": "CHAT",
            "combat": "COMBAT",
            "heals": "HEAL CHAIN",
            "vitals": "VITALS",
        }.get(str(channel or "").casefold(), "SYSTEM")

    def present(self, notice_id, text, reduce_motion=False, available=True,
                channel="system"):
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
        self._pending_channels.append(self._channel_label(channel))
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
        channel = (self._pending_channels.popleft()
                   if self._pending_channels else "SYSTEM")
        self._scroll_timer.stop()
        self._clear_timer.stop()
        self._fade_animation.stop()
        self._opacity_effect.setOpacity(1.0)
        self._label.setText(clean)
        self._channel.setText(channel)
        self._channel.setGeometry(1, 1, 82, self.height() - 2)
        self._channel.show()
        self._channel.raise_()
        self._label.adjustSize()
        self._label.setFixedHeight(self.height() - 2)
        self._label.show()
        self._channel.raise_()
        self.setToolTip(clean)
        spoken = f"{channel}: {clean}"
        self.setAccessibleName(f"Latest Vantage notification: {spoken}")
        self.setAccessibleDescription(
            f"Marquee notification; {len(self._pending)} more queued")
        self._announce_accessibly(spoken)
        # Combat summaries can be much wider than the rail and previously
        # remained visible for a long marquee pass. Give them a bounded,
        # readable dwell, then fade them out so the Quick Bar is available
        # for the next event. Reduced-motion users get the same timeout with
        # an immediate clear instead of an opacity animation.
        self._fade_on_expire = channel == "COMBAT" and not self._reduce_motion
        if channel == "COMBAT":
            self._clear_timer.setInterval(4500)
            self._clear_timer.start()
        if self._reduce_motion:
            self._moving = False
            # Preserve the meaningful type + source without moving or
            # squeezing a potentially unbounded message into this compact
            # surface. The complete notice remains in the accessible name.
            summary = " · ".join(clean.split(" · ")[:2])
            self._label.setText(summary)
            self._label.setFixedWidth(max(1, self.width() - 90))
            self._label.setGeometry(87, 1, self._label.width(), self.height() - 2)
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if channel != "COMBAT":
                self._clear_timer.setInterval(5000)
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
            self._label.setFixedWidth(max(1, self.width() - 90))
            self._label.setGeometry(87, 1, self._label.width(), self.height() - 2)
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._fade_on_expire = False
            self._clear_timer.setInterval(5000)
            self._clear_timer.start()

    def _expire_current(self):
        """Fade bounded notices, or clear immediately when motion is reduced."""
        if (self._fade_on_expire and self._label.isVisible() and
                self.isVisible()):
            self._scroll_timer.stop()
            self._fade_animation.start()
            return
        self._clear()

    def _advance(self):
        if not self.isVisible() or not self._label.isVisible():
            self._scroll_timer.stop()
            return
        self._label.move(self._label.x() - 2, 1)
        if self._label.x() + self._label.width() < 87:
            self._clear()

    def _clear(self):
        self._clear_current()
        if self._pending and self.isVisible():
            self._show_next()

    def _clear_current(self):
        self._scroll_timer.stop()
        self._clear_timer.stop()
        self._fade_animation.stop()
        self._opacity_effect.setOpacity(1.0)
        self._fade_on_expire = False
        self._moving = False
        self._label.clear()
        self._label.hide()
        self._channel.hide()
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


class QuickBarVolumeSlider(QSlider):
    """Native slider behavior with deterministic Vantage painting."""

    VISUAL_COLORS = {
        "rail": "#182127",
        "rail_outline": "#687A86",
        "fill": "#9A7541",
        "thumb_ring": "#C6A15A",
        "thumb_core": "#362916",
        "focus": "#D0A45B",
    }

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._last_focus_reason = None
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def focusInEvent(self, event):
        self._last_focus_reason = event.reason()
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, _event):
        """Paint a thin rail without platform-native light slider fills."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = {
            name: QColor(value) for name, value in self.VISUAL_COLORS.items()}

        left = 6.0
        right = max(left, float(self.width()) - 6.0)
        center_y = float(self.height()) / 2.0
        value_span = max(1, self.maximum() - self.minimum())
        progress = (self.value() - self.minimum()) / value_span
        if self.invertedAppearance():
            progress = 1.0 - progress
        thumb_x = left + (right - left) * max(0.0, min(1.0, progress))

        painter.setPen(QPen(
            colors["rail_outline"], 6.0, Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(left, center_y), QPointF(right, center_y))
        painter.setPen(QPen(
            colors["rail"], 4.0, Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(left, center_y), QPointF(right, center_y))
        if thumb_x > left:
            painter.setPen(QPen(
                colors["fill"], 4.0, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap))
            painter.drawLine(
                QPointF(left, center_y), QPointF(thumb_x, center_y))

        ring = colors["focus"] if self.hasFocus() else colors["thumb_ring"]
        if self.underMouse() or self.isSliderDown():
            ring = colors["focus"]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ring)
        painter.drawEllipse(QPointF(thumb_x, center_y), 5.0, 5.0)
        painter.setBrush(colors["thumb_core"])
        painter.drawEllipse(QPointF(thumb_x, center_y), 2.75, 2.75)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(colors["focus"], 2.0))
            painter.drawRoundedRect(
                1.0, 2.0, max(0.0, self.width() - 2.0),
                max(0.0, self.height() - 4.0), 4.0, 4.0)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class QuickBar(ParserWindow):
    """One taskbar-free surface for window toggles and tray commands."""

    name = "quickbar"
    _allow_clickthrough = False
    _LOG_ONLINE_DEBOUNCE_MS = 2000
    _DIALOG_ACTIONS = {
        "spell_library": ("_spell_library_dialog", "show_spell_library"),
        "mobile": ("_mobile_dialog_instance", "show_mobile_share"),
        "device_sync": ("_device_sync_dialog_instance", "show_device_sync"),
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
        self._update_presentation_signature = None
        self._announced_update_receipt = ""
        self._update_receipt_announcement_pending = False
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
        self._set_header_tab_order()
        # The logical buttons remain 27 px, while the inherited graphics view
        # scales their complete replica. Do not let QGraphicsView's scene size
        # hint become a large native minimum width.
        self._scale_view.setMinimumSize(0, 0)
        self._scale_view.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        for target in self._window_targets.values():
            target.installEventFilter(self)
            status_changed = getattr(target, "status_changed", None)
            if status_changed is not None and hasattr(status_changed, "connect"):
                status_changed.connect(self.refresh_state)
        tick = self._window_targets.get("tick")
        if tick is not None and hasattr(tick, "tray_state_changed"):
            tick.tray_state_changed.connect(self._server_tick_update)
        # Rebuild the authored strip first, then derive its scale from the
        # saved physical width. Using the stale static design height here made
        # every restart shrink a customized Quick Bar a second time.
        self._apply_quickbar_settings(preserve_scale=False)
        self.refresh_state()

    def _setup_actions(self):
        self._setup_volume_rocker()

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

        self._vitals_badge = QLabel("—", self._buttons["vitals"])
        self._vitals_badge.setObjectName("QuickBarProductBadge")
        self._vitals_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vitals_badge.setGeometry(15, 1, 8, 9)
        self._vitals_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._vitals_badge.show()
        vitals_dot = self._enabled_dots.get("vitals")
        if vitals_dot is not None:
            vitals_dot.move(2, 16)

        self._update_badge = QLabel("!", self._buttons["updates"])
        self._update_badge.setObjectName("QuickBarAlertBadge")
        self._update_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_badge.setGeometry(15, 1, 8, 9)
        self._update_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._update_badge.hide()
        self._vantage_ui_badge = QLabel("UP", self._buttons["vantage_ui"])
        self._vantage_ui_badge.setObjectName("QuickBarProductBadge")
        self._vantage_ui_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vantage_ui_badge.setGeometry(8, 1, 15, 9)
        self._vantage_ui_badge.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._vantage_ui_badge.hide()
        ui_dot = self._enabled_dots.get("vantage_ui")
        if ui_dot is not None:
            ui_dot.move(2, 16)

        support = self._buttons["support"]
        support.setProperty("Support", True)
        support.setStyle(support.style())
        support.setToolTip(
            "Like this project? Support it — Buy Me a Coffee")
        support.setAccessibleDescription(
            "Opens the Vantage support page in your default browser")
        reset_layout = self._buttons["reload_ui"]
        reset_layout.setToolTip(
            "Reset presentation: hide other windows, expand rolled panels, disable compact timers, and reset window and table layouts; gameplay data is preserved")
        reset_layout.setAccessibleDescription(
            "Opens a confirmation before resetting presentation settings only")
        sync_button = self._buttons["device_sync"]
        sync_button.setToolTip(
            "Sync My PCs · pair 2, 3 or more Vantage computers without an account")
        sync_button.setAccessibleDescription(
            "Opens the permanent Device Sync pairing window for settings, "
            "layouts, notes, and managed WTS or WTB buttons")
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

    def _setup_volume_rocker(self):
        """Add compact, branded master-audio controls to the header."""
        self.volume_rocker = QFrame()
        self.volume_rocker.setObjectName("QuickBarVolumeRocker")
        self.volume_rocker.setProperty("HeaderPriority", 100)
        self.volume_rocker.setAccessibleName("Notification audio controls")
        self.volume_rocker.setAccessibleDescription(
            "Contains Master Mute, notification volume, and its percentage")
        self.volume_rocker.setToolTip(
            "Master Mute and notification volume for WAV and spoken alerts")
        self.volume_rocker.setStyleSheet("""
            QFrame#QuickBarVolumeRocker {
                background: #11181D;
                border: 1px solid #40505C;
                border-radius: 5px;
            }
        """)

        layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)

        self.master_mute_button, self._master_mute_dot = \
            self._new_master_mute_control(self.volume_rocker)
        layout.addWidget(self.master_mute_button)

        self.volume_value_label = QLabel()
        self.volume_value_label.setObjectName("QuickBarVolumeValue")
        self.volume_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.volume_value_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume_value_label.setStyleSheet("""
            QLabel#QuickBarVolumeValue {
                color: #E6D7AB;
                background: transparent;
                border: 0;
                font-weight: 600;
            }
        """)
        self.volume_value_label.setToolTip(
            "Current notification volume; zero is silent but does not turn "
            "on Master Mute")
        label_width = self._configure_percentage_label(
            self.volume_value_label)
        # Preserve a usable slider while keeping the entire composite inside
        # the former 130 px header budget. A larger system font gives the
        # readout more room before the slider reaches its 44 px floor.
        slider_width = self._compact_volume_slider_width(label_width)
        self.volume_slider = QuickBarVolumeSlider()
        self._configure_volume_slider(
            self.volume_slider, width=slider_width)
        self.volume_value_label.setBuddy(self.volume_slider)
        layout.addWidget(self.volume_slider)
        layout.addWidget(self.volume_value_label)
        self.volume_rocker.setFixedSize(
            2 + 24 + 2 + slider_width + 2 + label_width + 2, 24)

        self.volume_rocker.setLayout(layout)
        self.menu_area.addWidget(self.volume_rocker)

        self._volume_save_timer = QTimer(self)
        self._volume_save_timer.setSingleShot(True)
        self._volume_save_timer.setInterval(180)
        self._volume_save_timer.timeout.connect(self._save_master_volume)
        self.volume_slider.valueChanged.connect(
            lambda value, slider=self.volume_slider:
            self._volume_slider_changed(value, slider))
        self.volume_slider.sliderReleased.connect(self._save_master_volume)
        self._overflow_master_mute_button = None
        self._overflow_master_mute_dot = None
        self._overflow_volume_slider = None
        self._overflow_volume_label = None
        self._overflow_keyboard_target = "mute"
        self._header_overflow_menu.installEventFilter(self)
        self._header_overflow_menu.aboutToShow.connect(
            self._queue_overflow_volume_focus)
        self._sync_volume_slider()
        self._sync_master_mute_controls()

    def _new_master_mute_control(self, parent):
        """Create one compact mute toggle with a persistent state marker."""
        button = QToolButton(parent)
        button.setObjectName("QuickBarMuteToggle")
        button.setAutoRaise(True)
        button.setCheckable(True)
        button.setFixedSize(24, 24)
        button.setIcon(game_icon("ph-mute"))
        button.setIconSize(QSize(15, 15))
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setStyleSheet("""
            QToolButton#QuickBarMuteToggle {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0;
            }
            QToolButton#QuickBarMuteToggle:hover {
                background: #202A31;
                border-color: #7A8992;
            }
            QToolButton#QuickBarMuteToggle:checked {
                background: #3A2B20;
                border-color: #B98A4A;
            }
            QToolButton#QuickBarMuteToggle:focus {
                background: #202A31;
                border: 2px solid #F0C778;
            }
            QToolButton#QuickBarMuteToggle:checked:focus {
                background: #3A2B20;
                border: 2px solid #F0C778;
            }
        """)
        dot = QFrame(button)
        dot.setObjectName("QuickBarMuteStateDot")
        dot.setFixedSize(6, 6)
        dot.move(16, 2)
        dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        dot.setStyleSheet("""
            QFrame#QuickBarMuteStateDot[State="off"] {
                background: transparent;
                border: 1px solid #778A96;
                border-radius: 3px;
            }
            QFrame#QuickBarMuteStateDot[State="on"] {
                background: #F0C778;
                border: 1px solid #4B3515;
                border-radius: 3px;
            }
        """)
        button.clicked.connect(self._toggle_master_mute)
        return button, dot

    @staticmethod
    def _configure_percentage_label(label):
        """Reserve the rendered 100% width plus readable side breathing room."""
        width = max(
            label.minimumSizeHint().width(),
            label.fontMetrics().horizontalAdvance("100%") + 8)
        label.setFixedWidth(width)
        return width

    @staticmethod
    def _compact_volume_slider_width(label_width):
        """Share the old 130 px rocker budget with mute and large text."""
        return max(44, min(64, 98 - max(0, int(label_width))))

    @staticmethod
    def _configure_volume_slider(slider, width):
        """Apply one compact, high-contrast Vantage slider presentation."""
        slider.setObjectName("QuickBarVolumeSlider")
        slider.setRange(0, 100)
        slider.setSingleStep(1)
        slider.setPageStep(10)
        slider.setTracking(True)
        slider.setFixedSize(width, 24)
        slider.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        slider.setAccessibleName("Notification volume")
        slider.setAccessibleDescription(
            "Scales every WAV and text to speech notification. Master Mute "
            "is a separate control.")
        slider.setToolTip(
            "Notification volume · Arrow keys 1% · Page Up/Down 10% · "
            "Home/End 0% or 100% · Master Mute remains separate")
        slider.setStyleSheet("""
            QSlider#QuickBarVolumeSlider {
                background: transparent;
                border: 0;
            }
        """)

    def _set_header_tab_order(self):
        """Keep keyboard traversal aligned with the visible title-bar order."""
        if (self.volume_rocker.isHidden() and
                self._header_overflow_button.isVisible()):
            QWidget.setTabOrder(
                self._button, self._header_overflow_button)
            QWidget.setTabOrder(
                self._header_overflow_button, self._settings_button)
        else:
            QWidget.setTabOrder(self._button, self.master_mute_button)
            QWidget.setTabOrder(
                self.master_mute_button, self.volume_slider)
            QWidget.setTabOrder(self.volume_slider, self._settings_button)
        QWidget.setTabOrder(self._settings_button, self._roll_button)
        QWidget.setTabOrder(self._roll_button, self._minimize_button)

    def _pack_header_controls(self):
        """Pack the title bar, then mirror its visible keyboard order."""
        super()._pack_header_controls()
        if hasattr(self, "volume_rocker"):
            self._set_header_tab_order()

    def _header_overflow_candidates(self, widgets):
        """Let the non-button volume composite participate in overflow."""
        candidates = super()._header_overflow_candidates(widgets)
        rocker = getattr(self, "volume_rocker", None)
        if (rocker is not None and rocker in widgets and
                not rocker.isHidden() and rocker not in candidates):
            candidates.insert(0, rocker)
        return candidates

    def _rebuild_header_overflow_menu(self):
        """Expose the hidden volume slider inside More actions as well."""
        self._overflow_master_mute_button = None
        self._overflow_master_mute_dot = None
        self._overflow_volume_slider = None
        self._overflow_volume_label = None
        self._overflow_keyboard_target = "mute"
        self._header_overflow_menu.setFocusProxy(None)
        super()._rebuild_header_overflow_menu()
        if self.volume_rocker not in self._header_overflowed:
            return
        menu = self._header_overflow_menu
        host = QFrame(menu)
        host.setObjectName("QuickBarOverflowVolume")
        host.setAccessibleName("Notification audio controls")
        host.setAccessibleDescription(
            "Contains Master Mute, notification volume, and its percentage")
        layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(6)
        mute_button, mute_dot = self._new_master_mute_control(host)
        slider = QuickBarVolumeSlider(host)
        self._configure_volume_slider(slider, width=116)
        label = QLabel(host)
        label.setObjectName("QuickBarVolumeValue")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._configure_percentage_label(label)
        label.setBuddy(slider)
        host.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        host.setFocusProxy(mute_button)
        layout.addWidget(mute_button)
        layout.addWidget(slider)
        layout.addWidget(label)
        host.setLayout(layout)
        menu.setFocusProxy(mute_button)
        action = QWidgetAction(menu)
        action.setText("Notification volume")
        action.setDefaultWidget(host)
        before = menu.actions()[0] if menu.actions() else None
        menu.insertAction(before, action)
        self._overflow_master_mute_button = mute_button
        self._overflow_master_mute_dot = mute_dot
        self._overflow_volume_slider = slider
        self._overflow_volume_label = label
        mute_button.installEventFilter(self)
        slider.installEventFilter(self)
        slider.valueChanged.connect(
            lambda value, control=slider:
            self._volume_slider_changed(value, control))
        slider.sliderReleased.connect(self._save_master_volume)
        self._sync_volume_slider()
        self._sync_master_mute_controls()

    def _queue_overflow_volume_focus(self):
        """Place keyboard users on the first embedded audio control."""
        button = self._overflow_master_mute_button
        if button is None:
            return

        def focus_audio_controls():
            try:
                if (self._header_overflow_menu.isVisible() and
                        button.isVisibleTo(self._header_overflow_menu)):
                    button.setFocus(Qt.FocusReason.TabFocusReason)
            except RuntimeError:
                return

        # QMenu applies its own active-action focus immediately after
        # aboutToShow. Reassert once that native popup setup is complete so
        # arrows, Page Up/Down, Home, and End reach the embedded QSlider.
        QTimer.singleShot(0, focus_audio_controls)
        QTimer.singleShot(20, focus_audio_controls)

    def _toggle_master_mute(self, _checked=False):
        """Toggle the authoritative audio kill switch, independent of volume."""
        self._application.toggle_audio_muted()
        self._sync_master_mute_controls()

    def _sync_master_mute_controls(self):
        """Mirror Master Mute into header and overflow affordances."""
        muted = audio_muted()
        controls = (
            (getattr(self, "master_mute_button", None),
             getattr(self, "_master_mute_dot", None)),
            (getattr(self, "_overflow_master_mute_button", None),
             getattr(self, "_overflow_master_mute_dot", None)),
        )
        state = "ON" if muted else "OFF"
        for button, dot in controls:
            if button is None:
                continue
            try:
                blocked = button.blockSignals(True)
                button.setChecked(muted)
                button.blockSignals(blocked)
                button.setProperty("State", state.casefold())
                button.setAccessibleName(f"Master Mute: {state}")
                button.setAccessibleDescription(
                    "Toggle all Vantage sound and speech. " +
                    ("All notification audio is muted." if muted else
                     "Notification audio is active."))
                button.setToolTip(
                    f"Master Mute {state} · " +
                    ("click to restore Vantage audio" if muted else
                     "click to silence all Vantage audio"))
                if dot is not None:
                    dot.setProperty("State", state.casefold())
                    dot.setAccessibleName(f"Master Mute {state} indicator")
                    style = dot.style()
                    style.unpolish(dot)
                    style.polish(dot)
                    dot.update()
                    dot.raise_()
            except RuntimeError:
                continue

    def _volume_slider_changed(self, value, source):
        """Apply changes live and coalesce durable writes while dragging."""
        value = set_master_volume(value)
        self._sync_volume_slider(value)
        if source.isSliderDown():
            self._volume_save_timer.stop()
        else:
            self._volume_save_timer.start()

    def _save_master_volume(self):
        """Persist the final slider value once after a drag or key burst."""
        self._volume_save_timer.stop()
        config.save()

    def _sync_volume_slider(self, value=None):
        """Mirror the authoritative setting without feedback or disk writes."""
        value = master_volume() if value is None else max(0, min(100, int(value)))
        sliders = [self.volume_slider]
        overflow_slider = getattr(self, "_overflow_volume_slider", None)
        if overflow_slider is not None:
            sliders.append(overflow_slider)
        for slider in sliders:
            try:
                blocked = slider.blockSignals(True)
                slider.setValue(value)
                slider.blockSignals(blocked)
            except RuntimeError:
                continue
        text = f"{value}%"
        self.volume_value_label.setText(text)
        self.volume_value_label.setAccessibleName(f"{value} percent")
        self.volume_value_label.setAccessibleDescription(
            "Readout for the adjacent notification volume slider")
        overflow_label = getattr(self, "_overflow_volume_label", None)
        if overflow_label is not None:
            try:
                overflow_label.setText(text)
                overflow_label.setAccessibleName(f"{value} percent")
            except RuntimeError:
                pass

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
            # Keep the horizontal launcher recoverable at the established
            # width and target scale. Adding a few authored header pixels
            # must not make the entire command strip (and every action
            # target in it) eligible to shrink further.
            0.375,
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
        overflow_controls = (
            getattr(self, "_overflow_master_mute_button", None),
            getattr(self, "_overflow_volume_slider", None),
        )
        if ((watched is self._header_overflow_menu or
             watched in overflow_controls) and
                event.type() == QEvent.Type.KeyPress and
                self._header_overflow_menu.isVisible()):
            mute_button = self._overflow_master_mute_button
            slider = self._overflow_volume_slider
            if mute_button is not None and slider is not None:
                key = event.key()
                if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                    reverse = (
                        key == Qt.Key.Key_Backtab or
                        bool(event.modifiers() &
                             Qt.KeyboardModifier.ShiftModifier))
                    current = QApplication.focusWidget()
                    if watched is self._header_overflow_menu:
                        target = mute_button if reverse else slider
                    elif reverse:
                        target = (mute_button if current is slider else slider)
                    else:
                        target = (slider if current is mute_button else
                                  mute_button)
                    reason = (Qt.FocusReason.BacktabFocusReason if reverse else
                              Qt.FocusReason.TabFocusReason)
                    self._overflow_keyboard_target = (
                        "slider" if target is slider else "mute")
                    target.setFocus(reason)
                    return True
                if ((watched is mute_button or
                     watched is self._header_overflow_menu) and
                        key in (Qt.Key.Key_Space, Qt.Key.Key_Return,
                                Qt.Key.Key_Enter)):
                    mute_button.click()
                    return True
                if (watched is not slider and not (
                        watched is self._header_overflow_menu and
                        self._overflow_keyboard_target == "slider")):
                    return super().eventFilter(watched, event)
                value = slider.value()
                if key == Qt.Key.Key_Home:
                    value = slider.minimum()
                elif key == Qt.Key.Key_End:
                    value = slider.maximum()
                elif key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
                    value += slider.singleStep()
                elif key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
                    value -= slider.singleStep()
                elif key == Qt.Key.Key_PageUp:
                    value += slider.pageStep()
                elif key == Qt.Key.Key_PageDown:
                    value -= slider.pageStep()
                else:
                    return super().eventFilter(watched, event)
                slider.setFocus(Qt.FocusReason.TabFocusReason)
                slider.setValue(max(
                    slider.minimum(), min(slider.maximum(), value)))
                return True
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
        prior_width_scale = (
            self.width() / max(1, self._design_size.width()))
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

        # Pending updates use a little more room to identify the product in
        # words. Reapply the presentation before measuring the authored strip
        # so orientation changes can never clip the capsule.
        product_names = tuple(filter(None, str(
            self._buttons["updates"].property("UpdateProducts") or ""
        ).split(",")))
        self._set_update_button_presentation(product_names)

        visible_widgets = [self.orientation_button]
        for key, button in self._buttons.items():
            visible = bool(settings.get(f"show_{key}", True))
            button.setVisible(visible)
            if visible:
                visible_widgets.append(button)
        self._sync_support_animation()
        self._sync_log_animation()

        tick_visible = bool(settings.get("show_server_tick", True))
        self.tick_readout.setVisible(tick_visible)
        rail_visible = bool(
            settings.get("show_notification_ticker", True) and not vertical)
        self.notification_rail.setVisible(rail_visible)
        self.notification_rail.set_motion_reduced(
            config.data["general"].get("reduce_motion", False))
        if tick_visible:
            visible_widgets.append(self.tick_readout)
        item_count = len(visible_widgets)
        margins = self.action_layout.contentsMargins()
        spacing = self.action_layout.spacing()
        # The 24 px rocker is created before the Quick Bar's first show. Make
        # the title layout consume its fixed target immediately so a later
        # settings refresh cannot grow the authored window by five pixels.
        self.menu_area.activate()
        self._menu_content.activate()
        if self._header_visible:
            header_height = self._menu.sizeHint().height()
            if not vertical:
                header_height = max(
                    header_height, self.volume_rocker.height())
        else:
            header_height = 0
        header_width = (
            self._compact_header_width() if self._header_visible else 0)

        if vertical:
            self.content.setAlignment(
                self.action_frame,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            action_width = (
                margins.left() + margins.right() +
                max((widget.width() for widget in visible_widgets), default=24))
            action_height = (
                margins.top() + margins.bottom() +
                sum(widget.height() for widget in visible_widgets) +
                max(0, item_count - 1) * spacing)
            design_size = QSize(
                max(action_width, header_width),
                header_height + action_height)
        else:
            self.content.setAlignment(
                self.action_frame,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            action_width = (
                margins.left() + margins.right() +
                sum(widget.width() for widget in visible_widgets) +
                max(0, item_count - 1) * spacing)
            action_height = (
                margins.top() + margins.bottom() +
                max((widget.height() for widget in visible_widgets), default=24))
            rail_width = max(120, action_width - 24)
            self.notification_rail.setFixedWidth(rail_width)
            design_size = QSize(
                max(120, action_width, header_width),
                header_height + action_height +
                (self.notification_rail.height() if rail_visible else 0))
        # Quick Bar height is content-derived. Preserve its horizontal scale
        # across temporary button visibility changes instead of taking the
        # smaller of width/height and accumulating a rounding shrink each time.
        self._set_design_size(design_size, preserve_scale=False)
        if preserve_scale and not self._collapsed:
            scale = max(
                self._effective_minimum_scale(), min(1.0, prior_width_scale))
            self.resize(
                round(design_size.width() * scale),
                round(design_size.height() * scale))
        self._update_uniform_scale()
        self._fit_to_available_screen()

    def _set_update_button_presentation(self, product_names=()):
        """Identify pending update products without relying on color alone."""
        products = tuple(product_names)
        receipt = str(getattr(
            self._application, "_last_update_success", "") or "").strip()
        vertical = self._orientation == "vertical"
        if products:
            if set(products) == {"Vantage", "VantageUI"}:
                text = "2" if vertical else "Vantage + UI"
            elif "VantageUI" in products:
                text = "UI" if vertical else "VantageUI"
            else:
                text = "APP" if vertical else "Vantage"
            badge_text = str(len(products))
            mode = "ready"
        elif receipt:
            text = "OK" if vertical else "Updated"
            badge_text = "✓"
            mode = "complete"
        else:
            text = ""
            badge_text = ""
            mode = "idle"

        button = self._buttons["updates"]
        if mode == "idle":
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            width = 24
        elif vertical:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            width = 30
        else:
            button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            width = max(58, min(
                112, button.fontMetrics().horizontalAdvance(text) + 31))
        button.setText(text)
        button.setFixedSize(width, 24)
        button.setProperty("UpdateMode", mode)
        self._update_badge.setText(badge_text)
        self._update_badge.setGeometry(max(1, width - 10), 1, 9, 10)
        self._update_badge.setVisible(mode in {"ready", "complete"})
        dot = self._enabled_dots.get("updates")
        if dot is not None:
            # The open-state marker owns the opposite corner from the badge.
            dot.move(2, 16)
        signature = (self._orientation, products, bool(receipt), width)
        changed = signature != self._update_presentation_signature
        self._update_presentation_signature = signature
        return changed

    def _announce_update_receipt(self, receipt):
        """Politely announce one visible post-restart receipt exactly once."""
        receipt = " ".join(str(receipt or "").split())
        if (not receipt or receipt == self._announced_update_receipt or
                self._update_receipt_announcement_pending or
                not self.isVisible()):
            return
        self._update_receipt_announcement_pending = True

        def announce():
            self._update_receipt_announcement_pending = False
            current = " ".join(str(getattr(
                self._application, "_last_update_success", "") or "").split())
            if (not self.isVisible() or current != receipt or
                    receipt == self._announced_update_receipt):
                return
            event = QAccessibleAnnouncementEvent(
                self._buttons["updates"], f"Update complete. {receipt}.")
            try:
                event.setPoliteness(
                    QAccessible.AnnouncementPoliteness.Polite)
            except (AttributeError, TypeError):
                pass
            try:
                QAccessible.updateAccessibility(event)
            except (AttributeError, RuntimeError, TypeError):
                return
            self._announced_update_receipt = receipt

        QTimer.singleShot(0, announce)

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
        self._sync_volume_slider()
        self._sync_master_mute_controls()
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
            label = str(button.property("BaseLabel") or
                        button.accessibleName())
            state = "open" if visible else "hidden"
            detail_getter = getattr(target, "quickbar_status", None)
            detail = str(detail_getter() if callable(detail_getter) else "").strip()
            if detail:
                button.setToolTip(
                    f"{label}: {detail} · window is {state} · click to toggle")
                button.setAccessibleDescription(
                    f"{detail}. Window is currently {state}")
                button.setProperty(
                    "MonitorState", detail.split(" ·", 1)[0].casefold())
                button.setStyle(button.style())
                if name == "vitals":
                    monitor_state = detail.split(" ·", 1)[0].upper()
                    self._vitals_badge.setText(
                        "✓" if monitor_state == "ACTIVE" else
                        "C" if monitor_state == "CALIBRATING" else "—")
                    self._vitals_badge.setToolTip(detail)
                    self._vitals_badge.raise_()
            else:
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
        sound_dialog = getattr(
            self._application, "_feature_settings_instances", {}).get(
                "Sounds")
        sound_open = bool(sound_dialog is not None and sound_dialog.isVisible())
        mute_button.blockSignals(True)
        mute_button.setChecked(sound_open)
        mute_button.blockSignals(False)
        mute_dot = self._enabled_dots.get("mute")
        if mute_dot is not None:
            mute_dot.setVisible(sound_open)
            if sound_open:
                mute_dot.raise_()
        blocked = str(getattr(
            self._application, "_last_audio_blocked", "None yet"))
        played = str(getattr(
            self._application, "_last_audio", "None yet"))
        sound_state = "all sounds muted" if muted else (
            f"master volume {master_volume()} percent")
        mute_button.setToolTip(
            "Open Sounds · " + sound_state + " · last played: " +
            played + " · last prevented: " + blocked)
        mute_button.setAccessibleDescription(
            "Open the Sounds center; " + sound_state)

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

        product_getter = getattr(
            self._application, "available_update_products", None)
        if callable(product_getter):
            update_products = product_getter()
        else:
            update_products = (
                {"Vantage": ""}
                if self._application.new_version_available() else {})
        update_ready = bool(update_products)
        update_button = self._buttons["updates"]
        companion_state = str(getattr(
            self._application, "_update_check_state", "idle"))
        ui_state = str(getattr(
            self._application, "_vantage_ui_update_state", "idle"))
        update_state = (
            "ready" if update_ready else
            "checking" if "checking" in (companion_state, ui_state) else
            "retrying" if "retrying" in (companion_state, ui_state) else
            "disabled" if companion_state == ui_state == "disabled" else
            "idle")
        update_button.setProperty("Alert", update_ready)
        update_button.setProperty("UpdateState", update_state)
        update_button.setProperty(
            "UpdateProducts", ",".join(update_products))
        presentation_changed = self._set_update_button_presentation(
            tuple(update_products))
        update_button.setStyle(update_button.style())
        if self._update_badge.isVisible():
            self._update_badge.raise_()
        ui_update_ready = "VantageUI" in update_products
        ui_button = self._buttons.get("vantage_ui")
        if ui_button is not None:
            ui_button.setProperty("UpdateReady", ui_update_ready)
            ui_button.setStyle(ui_button.style())
            self._vantage_ui_badge.setVisible(ui_update_ready)
            if ui_update_ready:
                self._vantage_ui_badge.raise_()
                ui_version = update_products.get("VantageUI", "")
                ui_button.setToolTip(
                    f"VantageUI {ui_version} update ready · click to toggle VantageUI")
                ui_button.setAccessibleName(
                    f"VantageUI update ready, version {ui_version}")
                ui_button.setAccessibleDescription(
                    "A verified VantageUI update is ready; click to toggle its window")
        if update_ready:
            product_copy = " and ".join(
                f"{name} {version}".strip()
                for name, version in update_products.items())
            tooltip = (
                f"{product_copy} ready · open verified updates")
            accessible_name = (
                f"Update ready for {product_copy}; open Updates")
            description = (
                f"Verified update available for {product_copy}")
        elif str(getattr(
                self._application, "_last_update_success", "") or "").strip():
            receipt = str(self._application._last_update_success)
            tooltip = f"{receipt} · click to open Updates"
            accessible_name = f"Update complete. {receipt}; open Updates"
            description = (
                "Persistent update receipt; opening Updates clears this receipt")
            self._announce_update_receipt(receipt)
        elif update_state == "checking":
            tooltip = (
                "Checking GitHub for verified Vantage and VantageUI updates…")
            accessible_name = "Checking Vantage and VantageUI updates"
            description = (
                "The one-minute update heartbeat is checking both products")
        elif update_state == "retrying":
            retry_products = []
            if companion_state == "retrying":
                retry_products.append("Vantage")
            if ui_state == "retrying":
                retry_products.append("VantageUI")
            retry_copy = " and ".join(retry_products) or "Updates"
            tooltip = (
                f"{retry_copy} check unavailable · retrying automatically")
            accessible_name = (
                f"{retry_copy} update check will retry automatically")
            description = (
                "The one-minute update heartbeat will retry the unavailable check")
        elif update_state == "disabled":
            tooltip = (
                "Automatic Vantage and VantageUI checks are off · click to check now")
            accessible_name = "Check Vantage and VantageUI updates manually"
            description = "The automatic update heartbeat is disabled in Settings"
        else:
            tooltip = (
                "Vantage and VantageUI checked automatically every minute · click now")
            accessible_name = "Check Vantage and VantageUI updates"
            description = "No verified update for either product is currently waiting"
        update_button.setToolTip(tooltip)
        update_button.setAccessibleName(accessible_name)
        update_button.setAccessibleDescription(description)

        if not str(getattr(
                self._application, "_last_update_success", "") or "").strip():
            self._announced_update_receipt = ""

        if presentation_changed:
            self._apply_quickbar_settings(preserve_scale=True)

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
            available=self.isVisible() and self.notification_rail.isVisible(),
            channel=getattr(
                self._application, "_quickbar_notice_channel", "system"))

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
            self._application.reset_ui_layout(
                parent=self, launcher=self._buttons.get(key))
        elif key == "link_logs":
            self._application.select_logs_folder(parent=self)
        elif key == "log_help":
            self._application.show_log_help()
        elif key == "mute":
            dialog = self._application.show_feature_settings(
                "Sounds", owner=self)
            if dialog not in self._dialog_targets:
                self._dialog_targets[dialog] = key
                dialog.installEventFilter(self)
        elif key == "quit":
            self._application.quit_vantage(confirm=True, parent=self)
        QTimer.singleShot(0, self.refresh_state)

    def restore_action_focus(self, key):
        """Restore keyboard focus through the embedded graphics proxy."""
        button = self._buttons.get(key)
        if button is None or not button.isEnabled():
            return False
        self._surface.setFocusProxy(button)
        self.action_frame.setFocusProxy(button)

        def focus_embedded_action():
            QApplication.setActiveWindow(self)
            self._scale_view.setFocus(Qt.FocusReason.OtherFocusReason)
            self._scale_scene.setFocus(Qt.FocusReason.OtherFocusReason)
            self._scale_proxy.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self._scale_scene.setActivePanel(self._scale_proxy)
            self._scale_scene.setFocusItem(
                self._scale_proxy, Qt.FocusReason.OtherFocusReason)
            self._scale_proxy.setFocus(Qt.FocusReason.OtherFocusReason)
            self._surface.setFocus(Qt.FocusReason.OtherFocusReason)
            button.setFocus(Qt.FocusReason.OtherFocusReason)

        def activate_launcher():
            self.show()
            self.raise_()
            self.activateWindow()
            self._scale_view.setFocus(Qt.FocusReason.OtherFocusReason)
            QTimer.singleShot(0, focus_embedded_action)

        # Restore the logical child immediately for keyboard tests and screen
        # readers, then repeat after the native window activation settles.
        focus_embedded_action()
        QTimer.singleShot(0, activate_launcher)
        return True

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
