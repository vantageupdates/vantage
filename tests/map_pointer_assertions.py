"""Assert the scene readout is painted, not merely marked visible by Qt."""
from PySide6.QtCore import QRect


def pointer_panel_rect(window, view):
    item = view._mouse_location
    bounds = item.deviceTransform(view.viewportTransform()).mapRect(item.boundingRect())
    return QRect(window._canvas_to_panel(view, bounds.topLeft().toPoint()),
                 window._canvas_to_panel(view, bounds.bottomRight().toPoint())).normalized()


def assert_pointer_pixels(window, view):
    item = view._mouse_location
    bounds = pointer_panel_rect(window, view)
    origin = window._scale_view.viewport().mapTo(window, bounds.topLeft())
    visible = window.grab().toImage()
    item.hide()
    hidden = window.grab().toImage()
    item.show()
    ratio = visible.devicePixelRatio()
    pixels = QRect(round(origin.x() * ratio), round(origin.y() * ratio),
                   round(bounds.width() * ratio), round(bounds.height() * ratio))
    pixels = pixels.intersected(visible.rect())
    changed = 0
    text = 0
    for y in range(pixels.top(), pixels.bottom() + 1):
        for x in range(pixels.left(), pixels.right() + 1):
            color = visible.pixelColor(x, y)
            if color != hidden.pixelColor(x, y):
                changed += 1
                if min(color.red(), color.green(), color.blue()) > 160:
                    text += 1
    assert changed >= 30, ('Pointer scene item is not painted', bounds, changed)
    assert text >= 10, ('Pointer text has no visible foreground pixels', bounds, text)
    return bounds
