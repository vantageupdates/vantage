"""Small, original icon set shared by every Vantage surface."""

from functools import lru_cache

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QIcon

from vantage.helpers import resource_path


WINDOW_ICONS = {
    "quickbar": "compact",
    "maps": "map",
    "spells": "bolt",
    "tick": "tick",
    "timers": "timer",
    "combat": "combat",
    "heals": "heal",
    "market": "market",
}


@lru_cache(maxsize=64)
def game_icon(name):
    """Return a bundled SVG icon; an empty icon keeps missing assets harmless."""
    return QIcon(resource_path(f"data/ui/icons/{name}.svg"))


def game_pixmap(name, size, widget=None):
    """Rasterize an SVG at the monitor's physical resolution for labels."""
    logical_size = max(1, int(size))
    try:
        dpr = float(widget.devicePixelRatioF()) if widget is not None else 0.0
    except (AttributeError, RuntimeError, TypeError, ValueError):
        dpr = 0.0
    if dpr <= 0:
        screen = QGuiApplication.primaryScreen()
        dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
    return game_icon(name).pixmap(
        QSize(logical_size, logical_size), max(1.0, dpr))
