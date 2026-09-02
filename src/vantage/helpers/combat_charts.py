"""Lightweight native charts for log-observable combat statistics."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


CHART_MODES = (
    ("Damage timeline", "damage_timeline"),
    ("Total damage", "damage_total"),
    ("Active DPS", "active_dps"),
    ("Healing timeline", "healing_timeline"),
    ("Tanking + healing", "tanking_timeline"),
)

SERIES_COLORS = (
    "#C9964C", "#7FA6C9", "#82B98D", "#C27670", "#A98BC7")


def _timeline_bins(encounter, predicate):
    duration = max(1, int(math.ceil(encounter.duration)))
    step = max(1, int(math.ceil(duration / 600)))
    count = max(2, int(math.ceil(duration / step)) + 1)
    values = [0.0] * count
    for event in encounter.events:
        if not predicate(event):
            continue
        offset = max(
            0.0, (event.timestamp - encounter.started_at).total_seconds())
        index = min(count - 1, int(offset // step))
        values[index] += max(0, int(event.amount or 0))
    return values, step


def _rolling(values, step, seconds=6):
    window = max(1, int(math.ceil(seconds / step)))
    return [
        sum(values[max(0, index - window + 1):index + 1]) /
        max(1, min(index + 1, window) * step)
        for index in range(len(values))]


def _average(values, step):
    total = 0.0
    result = []
    for index, value in enumerate(values):
        total += value
        result.append(total / max(1, (index + 1) * step))
    return result


def build_chart_data(encounter, mode, actor="Total"):
    """Return bounded chart-ready data without retaining raw log text."""
    if not encounter:
        return {
            "kind": "empty", "title": "No fight selected", "series": [],
            "labels": [], "unit": "", "step": 1}
    actor = str(actor or "Total")
    if mode in ("damage_total", "active_dps"):
        rows = []
        for stats in encounter.attackers.values():
            value = (
                stats.damage / max(1.0, stats.active_duration)
                if mode == "active_dps" else stats.damage)
            rows.append((stats.name, float(value)))
        rows.sort(key=lambda item: item[1], reverse=True)
        rows = rows[:20]
        return {
            "kind": "bars",
            "title": (
                f"Active DPS · {encounter.target}" if mode == "active_dps"
                else f"Total damage · {encounter.target}"),
            "series": [], "labels": rows,
            "unit": "DPS" if mode == "active_dps" else "damage", "step": 1,
        }

    if mode == "damage_timeline":
        values, step = _timeline_bins(
            encounter,
            lambda event: event.kind == "Damage" and (
                actor == "Total" or event.actor.casefold() == actor.casefold()))
        return {
            "kind": "line", "title": f"Damage over time · {actor}",
            "series": [
                {"name": "Damage / second",
                 "values": [value / step for value in values],
                 "color": SERIES_COLORS[0]},
                {"name": "Rolling 6s DPS", "values": _rolling(values, step),
                 "color": SERIES_COLORS[1]},
                {"name": "Average DPS", "values": _average(values, step),
                 "color": SERIES_COLORS[2]}],
            "labels": [], "unit": "damage / second", "step": step,
        }

    if mode == "healing_timeline":
        values, step = _timeline_bins(
            encounter,
            lambda event: event.kind == "Heal" and (
                actor == "Total" or event.actor.casefold() == actor.casefold()))
        return {
            "kind": "line", "title": f"Observed healing · {actor}",
            "series": [
                {"name": "Observed healing / second",
                 "values": [value / step for value in values],
                 "color": SERIES_COLORS[2]},
                {"name": "Rolling 6s HPS", "values": _rolling(values, step),
                 "color": SERIES_COLORS[1]},
                {"name": "Average HPS", "values": _average(values, step),
                 "color": SERIES_COLORS[0]}],
            "labels": [], "unit": "observed healing / second", "step": step,
        }

    incoming, step = _timeline_bins(
        encounter,
        lambda event: event.kind == "Incoming" and (
            actor == "Total" or event.target.casefold() == actor.casefold()))
    healing, _ = _timeline_bins(
        encounter,
        lambda event: event.kind == "Heal" and (
            actor == "Total" or event.target.casefold() == actor.casefold()))
    return {
        "kind": "line", "title": f"Tanking + observed healing · {actor}",
        "series": [
            {"name": "Damage in / second",
             "values": [value / step for value in incoming],
             "color": SERIES_COLORS[3]},
            {"name": "Rolling 6s DTPS", "values": _rolling(incoming, step),
             "color": SERIES_COLORS[0]},
            {"name": "Observed healing / second",
             "values": [value / step for value in healing],
             "color": SERIES_COLORS[2]}],
        "labels": [], "unit": "damage / observed healing", "step": step,
    }


class CombatChartWidget(QWidget):
    """Antialiased chart canvas with no QtCharts or web-engine dependency."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = build_chart_data(None, "damage_timeline")
        self.setObjectName("CombatChartCanvas")
        self.setMinimumSize(240, 120)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName("Combat chart")
        self.setToolTip(
            "Native lightweight chart; use the toolbar to change view or export PNG")

    def sizeHint(self):
        return QSize(520, 240)

    def set_data(self, data):
        self._data = data or build_chart_data(None, "damage_timeline")
        self.setAccessibleDescription(
            str(self._data.get("title") or "Combat chart"))
        self.update()

    @staticmethod
    def _format_value(value):
        value = float(value or 0)
        if abs(value) >= 1_000_000:
            return f"{value / 1_000_000:.1f}m"
        if abs(value) >= 1_000:
            return f"{value / 1_000:.1f}k"
        return f"{value:.0f}"

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0C0E11"))
        painter.setPen(QPen(QColor("#2D3238"), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)
        data = self._data
        title_font = painter.font()
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#E0C98F"))
        painter.drawText(10, 17, str(data.get("title") or "Combat chart"))
        title_font.setBold(False)
        painter.setFont(title_font)
        if data.get("kind") == "empty":
            painter.setPen(QColor("#92979D"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Select a current, last, selected, or session fight")
            return
        if data.get("kind") == "bars":
            self._paint_bars(painter, data)
        else:
            self._paint_lines(painter, data)

    def _paint_bars(self, painter, data):
        rows = list(data.get("labels") or [])
        if not rows:
            painter.setPen(QColor("#92979D"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No visible damage")
            return
        chart = self.rect().adjusted(10, 27, -12, -10)
        label_width = min(150, max(82, chart.width() // 3))
        bar_left = chart.left() + label_width
        bar_width = max(20, chart.right() - bar_left - 55)
        row_height = max(9.0, chart.height() / max(1, len(rows)))
        maximum = max(value for _label, value in rows) or 1.0
        for index, (label, value) in enumerate(rows):
            top = chart.top() + index * row_height + 1
            height = max(4.0, row_height - 3)
            painter.setPen(QColor("#C9C5BC"))
            painter.drawText(
                QRectF(chart.left(), top, label_width - 6, height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                str(label))
            track = QRectF(bar_left, top, bar_width, height)
            painter.fillRect(track, QColor("#171B20"))
            fill = QRectF(
                bar_left, top, max(1.0, bar_width * value / maximum), height)
            painter.fillRect(fill, QColor(SERIES_COLORS[index % len(SERIES_COLORS)]))
            painter.setPen(QColor("#ECE8E0"))
            painter.drawText(
                QRectF(bar_left + bar_width + 5, top, 50, height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._format_value(value))

    def _paint_lines(self, painter, data):
        series = list(data.get("series") or [])
        if not series or not any(item.get("values") for item in series):
            return
        chart = QRectF(self.rect().adjusted(42, 31, -12, -24))
        maximum = max((
            max(item.get("values") or [0]) for item in series), default=0) or 1.0
        painter.setPen(QPen(QColor("#252A30"), 1))
        for index in range(5):
            y = chart.bottom() - chart.height() * index / 4
            painter.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
            painter.setPen(QColor("#8F949A"))
            painter.drawText(
                QRectF(0, y - 8, chart.left() - 5, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                self._format_value(maximum * index / 4))
            painter.setPen(QPen(QColor("#252A30"), 1))
        count = max(len(item.get("values") or []) for item in series)
        step = max(1, int(data.get("step") or 1))
        painter.setPen(QColor("#8F949A"))
        for ratio in (0.0, .5, 1.0):
            x = chart.left() + chart.width() * ratio
            seconds = round(max(0, count - 1) * step * ratio)
            painter.drawText(
                QRectF(x - 24, chart.bottom() + 3, 48, 16),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                f"{seconds}s")
        for item in series:
            values = item.get("values") or []
            if not values:
                continue
            path = QPainterPath()
            for index, value in enumerate(values):
                x = chart.left() + chart.width() * index / max(1, len(values) - 1)
                y = chart.bottom() - chart.height() * float(value) / maximum
                if index:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
            painter.setPen(QPen(QColor(item.get("color")), 1.6))
            painter.drawPath(path)
        legend_x = chart.left()
        for item in series:
            painter.setPen(QPen(QColor(item.get("color")), 2))
            painter.drawLine(
                QPointF(legend_x, 23), QPointF(legend_x + 12, 23))
            painter.setPen(QColor("#B9B6AF"))
            label = str(item.get("name") or "Series")
            painter.drawText(legend_x + 16, 27, label)
            legend_x += min(155, 22 + painter.fontMetrics().horizontalAdvance(label))
