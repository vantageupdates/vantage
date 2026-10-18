"""Dense Complete Heal rail visualization."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QLinearGradient, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.parser import ScreenGeometryWatcher


class HealRailWidget(QWidget):
    """Paint animated per-tank CH rails without creating child windows."""

    def __init__(self, tracker, parent=None):
        super().__init__(parent)
        self.tracker = tracker
        self.paused = False
        self.own_marker = ""
        self.setMinimumHeight(88)
        self.setToolTip(
            "Each block moves right-to-left over the Complete Heal cast; "
            "the gold mark is the configured spacing and NEXT is the next marker")
        self.setAccessibleName("Complete Heal rotation rails")
        self.setAccessibleDescription(
            "Live visual timeline of Complete Heal calls grouped by tank. "
            "The Live tab provides the same information as text.")

    def set_paused(self, paused):
        self.paused = bool(paused)
        self.update()

    @staticmethod
    def _fit_text(
            painter, rect, text, color, bold=False,
            alignment=Qt.AlignmentFlag.AlignCenter):
        font = QFont(painter.font())
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(color)
        text = painter.fontMetrics().elidedText(
            str(text), Qt.TextElideMode.ElideRight, max(1, int(rect.width() - 4)))
        painter.drawText(rect, alignment, text)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        background = QLinearGradient(0, 0, 0, self.height())
        background.setColorAt(0.0, QColor("#111A20"))
        background.setColorAt(1.0, QColor("#080D11"))
        painter.fillRect(self.rect(), background)

        now = datetime.datetime.now()
        active = self.tracker.active(now)
        tanks = []
        for cast in reversed(active):
            if cast.tank not in tanks:
                tanks.append(cast.tank)
        if not tanks:
            card = QRectF(self.rect()).adjusted(12.5, 10.5, -12.5, -10.5)
            card_fill = QLinearGradient(card.topLeft(), card.bottomRight())
            card_fill.setColorAt(0.0, QColor("#17232A"))
            card_fill.setColorAt(1.0, QColor("#0D1419"))
            painter.setPen(QPen(QColor("#40515C"), 1.0))
            painter.setBrush(card_fill)
            painter.drawRoundedRect(card, 8.0, 8.0)

            icon_size = max(24.0, min(34.0, card.height() - 18.0))
            icon = QRectF(
                card.left() + 14.0,
                card.center().y() - icon_size / 2.0,
                icon_size, icon_size)
            painter.setPen(QPen(QColor("#B99A60"), 1.2))
            painter.setBrush(QColor("#202B31"))
            painter.drawEllipse(icon)
            painter.setPen(QPen(
                QColor("#E2BD72"), max(2.0, icon_size * .09),
                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            center = icon.center()
            arm = icon_size * .20
            painter.drawLine(
                int(center.x() - arm), int(center.y()),
                int(center.x() + arm), int(center.y()))
            painter.drawLine(
                int(center.x()), int(center.y() - arm),
                int(center.x()), int(center.y() + arm))

            text_left = icon.right() + 13.0
            text_width = max(1.0, card.right() - text_left - 10.0)
            title_rect = QRectF(
                text_left, card.center().y() - 18.0, text_width, 18.0)
            detail_rect = QRectF(
                text_left, card.center().y() + 1.0, text_width, 17.0)
            self._fit_text(
                painter, title_rect, "Waiting for Complete Heal calls",
                QColor("#F1EEE7"), bold=True,
                alignment=Qt.AlignmentFlag.AlignLeft |
                Qt.AlignmentFlag.AlignVCenter)
            self._fit_text(
                painter, detail_rect, "Watching your linked EverQuest log",
                QColor("#AEB9BE"),
                alignment=Qt.AlignmentFlag.AlignLeft |
                Qt.AlignmentFlag.AlignVCenter)
            return

        margin = 6.0
        row_gap = 4.0
        row_height = max(24.0, min(34.0, (
            self.height() - margin * 2 - row_gap * (len(tanks) - 1)) /
            max(1, len(tanks))))
        tank_width = max(52.0, min(86.0, self.width() * 0.16))
        next_width = max(48.0, min(
            painter.fontMetrics().horizontalAdvance("NEXT RAMP01") + 8,
            self.width() * 0.28))
        track_left = margin + tank_width + 5.0
        track_right = self.width() - margin - next_width - 5.0
        track_width = max(80.0, track_right - track_left)

        small_font = QFont(painter.font())
        small_font.setPointSizeF(max(6.0, painter.font().pointSizeF() - 1.0))
        painter.setFont(small_font)

        for row, tank in enumerate(tanks):
            top = margin + row * (row_height + row_gap)
            tank_rect = QRectF(margin, top, tank_width, row_height)
            track_rect = QRectF(track_left, top, track_width, row_height)
            next_rect = QRectF(track_right + 5.0, top, next_width, row_height)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#11191d"))
            painter.drawRoundedRect(tank_rect, 4, 4)
            painter.setBrush(QColor("#0d1417"))
            painter.drawRoundedRect(track_rect, 4, 4)
            painter.setBrush(QColor("#11191d"))
            painter.drawRoundedRect(next_rect, 4, 4)
            self._fit_text(
                painter, tank_rect, tank, QColor("#b7c0c3"), bold=True)

            painter.setPen(QPen(QColor("#58666C"), 1.0))
            for second in range(1, 10):
                x = track_left + track_width * second / 10.0
                painter.drawLine(int(x), int(top + 3), int(x), int(top + row_height - 3))
            interval_x = track_right - track_width * self.tracker.interval / 10.0
            painter.setPen(QPen(QColor("#bba35f"), 1.4))
            painter.drawLine(
                int(interval_x), int(top + 1),
                int(interval_x), int(top + row_height - 1))

            casts = [cast for cast in active if cast.tank == tank]
            for cast in casts:
                elapsed = min(
                    float(self.tracker.cast_seconds), cast.elapsed(now))
                progress = elapsed / max(0.1, float(self.tracker.cast_seconds))
                width = max(
                    18.0,
                    track_width * self.tracker.interval /
                    max(1.0, float(self.tracker.cast_seconds)))
                x = track_right - width - progress * track_width
                block = QRectF(x, top + 3.0, width, row_height - 6.0)
                painter.save()
                painter.setClipRect(track_rect)
                if cast.interrupted:
                    color = QColor("#955257")
                elif cast.cleric.casefold() == "you":
                    color = QColor("#80672F")
                else:
                    color = QColor("#3f6f59")
                if self.paused:
                    color.setAlpha(120)
                border = QPen(color.lighter(135), 1.0)
                if cast.interrupted:
                    border.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(border)
                painter.setBrush(color)
                painter.drawRoundedRect(block, 3, 3)
                self._fit_text(
                    painter, block,
                    f"!{cast.marker}" if cast.interrupted else cast.marker,
                    QColor("#f0f2ed"), bold=True)
                painter.restore()

            latest = max(casts, key=lambda value: value.started_at)
            next_marker = self.tracker.next_marker(tank, latest.marker)
            own = (self.own_marker or self.tracker.local_marker).upper()
            next_color = (
                QColor("#ddc46f") if own and next_marker == own else
                QColor("#a0acaf"))
            self._fit_text(
                painter, next_rect, f"NEXT {next_marker}", next_color,
                bold=bool(own and next_marker == own))

        if self.paused:
            painter.setPen(QColor("#d4bd75"))
            painter.drawText(
                QRectF(0, 0, self.width() - 6, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                "PAUSED")


class HealChainOverlay(QWidget):
    """Independent, log-driven CH rails sharing the monitor's one tracker."""

    hidden = Signal()
    settings_requested = Signal()

    def __init__(self, tracker):
        # No QWidget owner: hiding the main monitor must not hide this window.
        super().__init__()
        self.tracker = tracker
        self._drag_offset = None
        self.setObjectName("HealChainOverlay")
        self.setWindowTitle("Heal Chain overlay")
        self.setWindowFlags(Qt.WindowType.Tool |
                            Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAccessibleName("Live Heal Chain overlay")
        # Reuse the existing rail palette; point sizes follow display scaling.
        self.setStyleSheet("""
            QWidget#HealChainOverlay { background: #10171C; border: 1px solid #40515C; }
            #HealChainOverlay QLabel { color: #F1EEE7; background: transparent; border: none; font-size: 12pt; }
            #HealChainOverlay QPushButton { font-size: 10pt; padding: 4px 8px; }
            #HealChainOverlay QLabel#HealChainOverlayTitle { color: #AEB9BE; font-size: 10pt; padding: 4px; }
            #HealChainOverlayTitle:focus { border: 2px solid #F0C778; }
            #HealChainOverlay QPushButton:focus { border: 2px solid #F0C778; }
            #HealChainOverlay QLabel#HealChainOverlayState { color: #E2BD72; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(5)
        header = QHBoxLayout()
        self.title = QLabel("HEAL CHAIN · drag to move")
        self.title.setObjectName("HealChainOverlayTitle")
        self.title.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.title.setCursor(Qt.CursorShape.SizeAllCursor)
        self.title.setAccessibleName("Move Heal Chain overlay")
        self.title.setAccessibleDescription(
            "Drag to move, or focus and use arrow keys. Escape hides the overlay.")
        self.title.setToolTip("Drag to move; keyboard: Tab here, then use arrow keys")
        self.title.installEventFilter(self)
        header.addWidget(self.title, 1)
        self.settings_button = QPushButton("Settings")
        self.settings_button.setAccessibleName("Open Heal Chain overlay settings")
        self.settings_button.setToolTip(
            "Open Heal Chain settings to change overlay opacity, position and monitoring")
        self.settings_button.clicked.connect(
            lambda _checked=False: self.settings_requested.emit())
        header.addWidget(self.settings_button)
        self.hide_button = QPushButton("Hide")
        self.hide_button.setAccessibleName("Hide Heal Chain overlay")
        self.hide_button.setToolTip("Hide this overlay; monitoring continues")
        self.hide_button.clicked.connect(self.close)
        header.addWidget(self.hide_button)
        layout.addLayout(header)
        self.state = QLabel("WAITING FOR CALLS")
        self.state.setObjectName("HealChainOverlayState")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.rails = HealRailWidget(tracker)
        rail_font = QFont(self.font())
        rail_font.setPointSizeF(max(12.0, rail_font.pointSizeF()))
        self.rails.setFont(rail_font)
        self.rails.setStyleSheet("font-size: 12pt;")
        self.rail_area = QScrollArea()
        self.rail_area.setWidgetResizable(True)
        self.rail_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.rail_area.setWidget(self.rails)
        self.rail_area.setMinimumHeight(88)
        self.rail_area.setMaximumHeight(160)
        self.rail_area.setAccessibleName("Heal Chain tank rails")
        layout.addWidget(self.rail_area, 1)
        self.current = QLabel("Listening for Complete Heal announcements")
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        self.next_call = QLabel("Expected next: waiting for a call")
        self.next_call.setWordWrap(True)
        layout.addWidget(self.next_call)
        self._escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._escape.activated.connect(self.close)
        QWidget.setTabOrder(self.title, self.settings_button)
        QWidget.setTabOrder(self.settings_button, self.hide_button)
        self.resize(500, 240)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_position)
        self._screen_geometry_watcher = ScreenGeometryWatcher(
            self, self._recover_screen_geometry)
        position = config.data["heals"].get("overlay_position", [580, 460])
        self.move(*position)
        self._recover_screen_geometry()

    def refresh(self, now, paused=False, enabled=True, own_marker=""):
        self.rails.own_marker = own_marker
        self.rails.set_paused(paused or not enabled)
        active = self.tracker.active(now)
        tanks = {cast.tank for cast in active}
        self.rails.setMinimumHeight(max(88, len(tanks) * 38 + 12))
        latest = max(active, key=lambda cast: cast.started_at, default=None)
        if not enabled or paused:
            self.state.setText("MONITOR OFF" if not enabled else "MONITORING PAUSED")
            self.current.setText("New calls are not being read.")
            self.next_call.setText("Resume monitoring in Heal Chain.")
        elif latest is None:
            self.state.setText("WAITING FOR CALLS")
            self.current.setText("No active Complete Heal calls")
            self.next_call.setText("Expected next: waiting for a call")
        else:
            marker = self.tracker.next_marker(latest.tank, latest.marker)
            cleric = self.tracker.next_cleric(latest.tank, latest.marker)
            own = (own_marker or self.tracker.local_marker).upper()
            your_turn = bool(marker and own == marker)
            self.state.setText(
                "CAST INTERRUPTED" if latest.interrupted else
                "YOUR MARKER NEXT" if your_turn else "CHAIN ACTIVE")
            remaining = latest.remaining(now, self.tracker.cast_seconds)
            cast_time = "interrupted" if latest.interrupted else f"{remaining:.1f}s cast remaining"
            self.current.setText(
                f"{latest.tank} · {latest.marker}: {latest.cleric} · {cast_time}")
            due = max(0.0, self.tracker.interval - latest.elapsed(now))
            expected = marker or "unknown marker"
            if your_turn:
                expected += " · You"
            elif cleric:
                expected += f" · {cleric}"
            timing = f"in {due:.1f}s" if due > 0 else "call due"
            self.next_call.setText(f"Expected next: {expected} · {timing}")
        self.current.setAccessibleName(self.current.text())
        self.next_call.setAccessibleName(self.next_call.text())
        self.state.setAccessibleName(self.state.text())
        self.next_call.setToolTip(
            "Prediction from observed order and configured spacing, not a confirmed cast. "
            "Cleric names appear only after their marker has been seen on this tank.")

    def apply_settings(self):
        settings = config.data["heals"]
        self.setWindowOpacity(settings.get("overlay_opacity", 94) / 100)
        if settings.get("overlay_enabled", False):
            self._recover_screen_geometry()
            self.show()
        else:
            self.hide()

    def reset_position(self):
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.left() + 24, area.top() + 24)
            self._recover_screen_geometry()
            self._save_position()

    def _recover_screen_geometry(self):
        if self._drag_offset is not None:
            self._screen_geometry_watcher.defer()
            return
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
            self.move(min(max(self.x(), area.left()), max(area.left(), area.right() - self.width() + 1)),
                      min(max(self.y(), area.top()), max(area.top(), area.bottom() - self.height() + 1)))

    def _save_position(self):
        self._save_timer.stop()
        config.data["heals"]["overlay_position"] = [self.x(), self.y()]
        config.save()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible() and hasattr(self, "_save_timer"):
            self._save_timer.start()

    def closeEvent(self, event):
        self._save_position()
        if config.APP_EXIT:
            # Application/update shutdown is not a request to disable the overlay.
            event.accept()
            return
        self.hide()
        self.hidden.emit()
        event.ignore()

    def eventFilter(self, watched, event):
        if watched is self.title:
            kind = event.type()
            if kind == QEvent.Type.KeyPress:
                moves = {Qt.Key.Key_Left: (-10, 0), Qt.Key.Key_Right: (10, 0),
                         Qt.Key.Key_Up: (0, -10), Qt.Key.Key_Down: (0, 10)}
                if event.key() in moves:
                    self.move(self.pos() + QPoint(*moves[event.key()]))
                    self._recover_screen_geometry()
                    return True
            elif kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = event.globalPosition().toPoint() - self.pos()
                return True
            elif kind == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            elif kind == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = None
                self._recover_screen_geometry()
                self._save_position()
                return True
        return super().eventFilter(watched, event)
