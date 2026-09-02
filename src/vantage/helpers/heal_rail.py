"""Dense Complete Heal rail visualization."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget


class HealRailWidget(QWidget):
    """Paint animated per-tank CH rails without creating child windows."""

    def __init__(self, tracker, parent=None):
        super().__init__(parent)
        self.tracker = tracker
        self.paused = False
        self.setMinimumHeight(88)
        self.setToolTip(
            "Each block moves right-to-left over the Complete Heal cast; "
            "the gold mark is the configured spacing and NEXT is the next marker")
        self.setAccessibleName("Animated Complete Heal rails")

    def set_paused(self, paused):
        self.paused = bool(paused)
        self.update()

    @staticmethod
    def _fit_text(painter, rect, text, color, bold=False):
        font = QFont(painter.font())
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(text))

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor("#0a0f12"))

        now = datetime.datetime.now()
        active = self.tracker.active(now)
        tanks = []
        for cast in reversed(active):
            if cast.tank not in tanks:
                tanks.append(cast.tank)
        if not tanks:
            painter.setPen(QColor("#7e898d"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Waiting for Complete Heal announcements")
            return

        margin = 6.0
        row_gap = 4.0
        row_height = max(24.0, min(34.0, (
            self.height() - margin * 2 - row_gap * (len(tanks) - 1)) /
            max(1, len(tanks))))
        tank_width = max(52.0, min(86.0, self.width() * 0.16))
        next_width = max(48.0, min(72.0, self.width() * 0.13))
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

            painter.setPen(QPen(QColor("#263236"), 1.0))
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
                    color = QColor("#743f42")
                elif cast.cleric.casefold() == "you":
                    color = QColor("#8a7338")
                else:
                    color = QColor("#3f6f59")
                if self.paused:
                    color.setAlpha(120)
                painter.setPen(QPen(color.lighter(125), 1.0))
                painter.setBrush(color)
                painter.drawRoundedRect(block, 3, 3)
                self._fit_text(
                    painter, block, cast.marker, QColor("#f0f2ed"), bold=True)
                painter.restore()

            latest = max(casts, key=lambda value: value.started_at)
            next_marker = self.tracker.next_marker(tank, latest.marker)
            own = self.tracker.local_marker.upper()
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
