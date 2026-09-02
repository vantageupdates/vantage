"""EverQuest Velious square spell-icon atlas helpers."""

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPainterPath, QPixmap

from vantage.helpers import resource_path


def spell_icon_coordinates(icon_index):
    """Map a zero-based EQ icon id to its 40×40 Velious icon cell."""
    icon_index = max(0, int(icon_index))
    file_number = icon_index // 36 + 1
    slot = icon_index % 36
    return file_number, (slot % 6) * 40, (slot // 6) * 40


def spell_icon_pixmap(icon_index, size=20):
    """Render a crisp Velious icon with a restrained rounded silhouette."""
    screen = QGuiApplication.primaryScreen()
    dpr = max(1.0, float(
        screen.devicePixelRatio() if screen is not None else 1.0))
    physical_size = max(1, round(size * dpr))
    file_number, x, y = spell_icon_coordinates(icon_index)
    sheet = QPixmap(resource_path(
        f'data/spells/spells0{file_number}.png'))
    scaled = sheet.copy(QRect(x, y, 40, 40)).scaled(
            physical_size, physical_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            # Do not blur the pixel art; this matches EverQuest and nParse.
            Qt.TransformationMode.FastTransformation)

    rounded = QPixmap(physical_size, physical_size)
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    radius = max(3.0 * dpr, physical_size * 0.16)
    clip = QPainterPath()
    clip.addRoundedRect(
        QRectF(0.5 * dpr, 0.5 * dpr,
               physical_size - dpr, physical_size - dpr), radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    rounded.setDevicePixelRatio(dpr)
    return rounded
