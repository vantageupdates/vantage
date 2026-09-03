"""Dense Complete Heal rail visualization."""

from __future__ import annotations

import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
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
        painter.drawText(rect, alignment, str(text))

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
