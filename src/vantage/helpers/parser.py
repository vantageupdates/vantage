import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QCursor, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QComboBox, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPushButton, QFrame, QGraphicsItem,
    QGraphicsOpacityEffect, QGraphicsScene, QGraphicsView, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget)

from vantage.helpers import config
from vantage.helpers.icons import WINDOW_ICONS, game_icon, game_pixmap
from vantage.helpers.scaled_tooltip import (
    forward_scaled_tooltip, sync_scaled_hover_tooltip)


DESIGN_SIZES = {
    "quickbar": QSize(590, 62),
    "maps": QSize(400, 400),
    # The 260 px logical width fits every authored header control. Physical
    # resizing still scales the entire replica down uniformly.
    "spells": QSize(260, 400),
    "tick": QSize(260, 142),
    "timers": QSize(520, 360),
    "combat": QSize(520, 300),
    "heals": QSize(520, 220),
    "market": QSize(980, 620),
}


WM_ENTERSIZEMOVE = 0x0231
WM_SIZING = 0x0214
WM_EXITSIZEMOVE = 0x0232
WMSZ_LEFT = 1
WMSZ_RIGHT = 2
WMSZ_TOP = 3
WMSZ_TOPLEFT = 4
WMSZ_TOPRIGHT = 5
WMSZ_BOTTOM = 6
WMSZ_BOTTOMLEFT = 7
WMSZ_BOTTOMRIGHT = 8


def independent_sizing_rect(
        edge, rect, logical_size, minimum_scale=.25,
        chrome=(0, 0), device_scale=1.0, minimum_width=0):
    """Clamp a WM_SIZING rectangle without changing an untouched axis.

    A vertical edge changes only height, a horizontal edge changes only width,
    and a corner may change both.  This is important for list panels: pulling
    the bottom edge reveals more rows instead of also changing their width and
    font scale.
    """
    left, top, right, bottom = (int(value) for value in rect)
    dpr = max(.25, float(device_scale or 1.0))
    chrome_width = max(0, int(round(float(chrome[0]) * dpr)))
    chrome_height = max(0, int(round(float(chrome[1]) * dpr)))
    minimum_width_pixels = max(
        1,
        int(round(logical_size.width() * dpr * float(minimum_scale))) +
        chrome_width,
        int(round(max(0, int(minimum_width)) * dpr)) + chrome_width)
    minimum_height = max(1, int(round(
        logical_size.height() * dpr * float(minimum_scale))) + chrome_height)

    if right - left < minimum_width_pixels:
        if edge in (WMSZ_LEFT, WMSZ_TOPLEFT, WMSZ_BOTTOMLEFT):
            left = right - minimum_width_pixels
        else:
            right = left + minimum_width_pixels
    if bottom - top < minimum_height:
        if edge in (WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT):
            top = bottom - minimum_height
        else:
            bottom = top + minimum_height
    return left, top, right, bottom


if sys.platform == "win32":
    class _WindowsRect(ctypes.Structure):
        _fields_ = (
            ("left", wintypes.LONG), ("top", wintypes.LONG),
            ("right", wintypes.LONG), ("bottom", wintypes.LONG))


class ParserContextMenuRouter(QObject):
    """Route background context menus with one application filter, not six."""

    def __init__(self, application):
        super().__init__(application)
        self._windows = []
        application.installEventFilter(self)

    def register(self, window):
        if window not in self._windows:
            self._windows.append(window)

    def eventFilter(self, watched, event):
        if (event.type() != QEvent.Type.ContextMenu
                or not isinstance(watched, QWidget)):
            return False
        self._windows = [window for window in self._windows if window]
        for window in self._windows:
            if (window._is_window_descendant(watched)
                    and not window._preserve_child_context_menu(watched)):
                window._show_window_context_menu(event.globalPos())
                return True
        return False


class ParserResizeHandle(QWidget):
    """Invisible resize affordance for one frameless panel edge or corner."""

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

    def __init__(self, direction, panel):
        super().__init__(panel)
        self.direction = str(direction)
        self.panel = panel
        label = self.direction.replace("_", " ")
        self.setObjectName(f"ParserWindowResize_{self.direction}")
        self.setCursor(self.CURSORS[self.direction])
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(f"Resize window from {label}")
        self.setToolTip(f"Drag the {label} edge to resize this window")

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.panel._resize_handles_enabled()):
            self.panel._start_panel_resize(
                self.direction, event.globalPosition().toPoint())
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.panel._drag_panel_resize(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.mouseGrabber() is self:
                self.releaseMouse()
            self.panel._stop_panel_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ParserWindow(QWidget):
    content = None
    menu_area = None
    name = None

    _always_on_top = True
    _auto_hide_menu = True
    _button = None
    _clickthrough = False
    _collapsed = False
    _frameless = True
    _geometry = None
    _menu = None
    _menu_content = None
    _parser_menu_area = None
    _title = None
    _toggled = False
    _window_flush = None
    _window_opacity = 80
    # Overlay panels may optionally let clicks pass through to EverQuest.
    # Interaction-heavy windows (for example Market) override this.
    _allow_clickthrough = True
    # Parser panels keep one immutable logical width. Horizontal resizing scales
    # the complete replica; vertical resizing changes the logical viewport height
    # so lists reveal or hide rows without changing font or control size.
    _native_surface = False
    # Dense overlay bodies may be scaled down, but selected windows can keep
    # their title chrome at a readable physical size. Subclasses opt in when
    # they are routinely used as narrow HUD panels.
    _keep_header_readable = False
    _minimum_readable_width = 0
    # The complete logical surface can be reduced to one quarter size.  This
    # is deliberately a uniform transform: controls, text, rows and spacing
    # all remain in the same places instead of switching to a compact/reflowed
    # layout.  A small physical floor keeps a rolled or resized panel possible
    # to recover with the mouse.
    _minimum_scale = 0.25

    def __init__(self, **kwargs):
        if not self.name:
            self.name = kwargs.get("name", None)
            if not self.name:
                raise AttributeError(
                    "'name' is a required attribute that must be set via **kwargs or in the partent class."
                )
        super().__init__()

        # Set vars from config
        self._always_on_top = config.data.get(self.name, {}).get("always_on_top", True)
        self._auto_hide_menu = config.data.get(self.name, {}).get("auto_hide_menu", True)
        self._clickthrough = bool(
            self._allow_clickthrough and
            config.data.get(self.name, {}).get("clickthrough", False))
        # The selected startup mode is applied after subclasses finish layout.
        self._collapsed = False
        self._frameless = config.data.get(self.name, {}).get("frameless", True)
        self._geometry = config.data.get(self.name, {}).get("geometry", [0,0,200,400])
        self._toggled = config.data.get(self.name, {}).get("toggled", True)
        self._window_flush = config.data.get("general", {}).get("window_flush", True)
        self._window_opacity = config.data.get(self.name, {}).get("opacity", 80)

        # Setup UI
        self._button = QPushButton()
        self._button.setIcon(game_icon("frame"))
        self._button.setIconSize(QSize(13, 13))
        self._button.setObjectName("ParserWindowMoveButton")
        self._button.setAccessibleName("Toggle window frame")
        self._button.setToolTip("Show or hide the Windows frame")
        self._button.clicked.connect(self._toggle_frame)

        self._title = QLabel()
        self._title.setText(self.name.title())
        self._title.setObjectName("ParserWindowTitle")
        self._title.setAccessibleName("Window title; drag to move")
        self._title.setToolTip("Drag this bar to move the window")
        self._title.setMinimumWidth(0)
        self._title.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._title.mousePressEvent = self._start_move

        self._title_icon = QLabel()
        self._title_icon.setObjectName("ParserWindowTitleIcon")
        self._refresh_title_icon()
        self._title_icon.setAccessibleName("")

        self.menu_area = QHBoxLayout()
        self.menu_area.setContentsMargins(1, 0, 1, 0)
        self.menu_area.setSpacing(2)
        self._header_menu_base_margins = (1, 0, 1, 0)
        self._header_menu_base_spacing = 2

        self._parser_menu_area = QWidget()
        self._parser_menu_area.setObjectName("ParserWindowMenu")
        self._parser_menu_area.setLayout(self.menu_area)

        self._menu_content = QHBoxLayout()
        self._menu_content.setSpacing(2)
        # Keep controls clear of the 9 px rounded window mask. This margin is
        # part of the logical replica, so it remains proportional when scaled.
        self._menu_content.setContentsMargins(6, 0, 6, 0)
        self._header_root_base_margins = (6, 0, 6, 0)
        self._header_root_base_spacing = 2
        self._header_widget_metrics = {}
        self._header_metric_factor = 1.0
        self._menu_content.addWidget(self._button, 0)
        self._menu_content.addWidget(self._title_icon, 0)
        self._menu_content.addWidget(self._title, 1)
        self._menu_content.addWidget(self._parser_menu_area, 0)
        self._header_overflow_button = QToolButton()
        # Reuse the established chrome-button metrics without introducing a
        # second visual family into the tiny title strip.
        self._header_overflow_button.setObjectName(
            "ParserWindowSettingsButton")
        self._header_overflow_button.setIcon(game_icon("ph-stack"))
        self._header_overflow_button.setIconSize(QSize(13, 13))
        self._header_overflow_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        self._header_overflow_button.setAccessibleName(
            "More window actions")
        self._header_overflow_button.setToolTip(
            "Open header actions that do not fit beside the window title")
        self._header_overflow_menu = QMenu(self._header_overflow_button)
        self._header_overflow_menu.setToolTipsVisible(True)
        self._header_overflow_menu.aboutToShow.connect(
            self._rebuild_header_overflow_menu)
        self._header_overflow_button.setMenu(self._header_overflow_menu)
        self._header_overflow_button.hide()
        self._menu_content.addWidget(self._header_overflow_button)
        self._settings_button = QToolButton()
        self._settings_button.setObjectName("ParserWindowSettingsButton")
        self._settings_button.setIcon(game_icon("settings"))
        self._settings_button.setIconSize(QSize(13, 13))
        self._settings_button.setAccessibleName("Settings for this window")
        self._settings_button.setToolTip(
            "Adjust this window here, or open all settings for this tool")
        self._settings_button.clicked.connect(self._show_inline_settings)
        self._menu_content.addWidget(self._settings_button)
        self._roll_button = QPushButton()
        self._roll_button.setObjectName("ParserWindowRollButton")
        self._roll_button.setIcon(game_icon("roll"))
        self._roll_button.setIconSize(QSize(13, 13))
        self._roll_button.setAccessibleName("Roll up panel")
        self._roll_button.setToolTip("Roll up the panel and keep only its header")
        self._roll_button.clicked.connect(self._toggle_rollup)
        self._menu_content.addWidget(self._roll_button)
        self._minimize_button = QPushButton()
        self._minimize_button.setIcon(game_icon("minimize"))
        self._minimize_button.setIconSize(QSize(13, 13))
        self._minimize_button.setObjectName("ParserWindowMinimizeButton")
        self._minimize_button.setAccessibleName("Hide in system tray")
        self._minimize_button.setToolTip("Hide this window in the system tray")
        self._minimize_button.clicked.connect(self._minimize_to_tray)
        self._menu_content.addWidget(self._minimize_button)

        self._menu = QWidget()
        self._menu.setObjectName("ParserWindowMenuReal")
        self._menu.setLayout(self._menu_content)
        self._menu_effect = None
        # Keep the header in the immutable logical layout at all times. Auto
        # hide changes only opacity/input, never geometry, so entering a tiny
        # panel to resize it cannot push or rearrange its content.
        self._menu.setVisible(True)

        self.content = QVBoxLayout()
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(0)
        self.content.addWidget(self._menu, 0)

        self._set_header_revealed(not self._auto_hide_menu)

        # Every parser owns one canonical logical surface. The graphics view
        # applies a vector transform to that complete interactive surface;
        # QGraphicsProxyWidget maps pointer and keyboard events back into the
        # original controls, even when the panel is very small.
        self._design_size = DESIGN_SIZES.get(
            self.name, QSize(max(220, self._geometry[2]),
                             max(200, self._geometry[3])))
        self._surface = QWidget()
        self._surface.setObjectName("ParserWindowSurface")
        self._surface.setLayout(self.content)
        self._surface.setFixedSize(self._design_size)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._scale_scene = QGraphicsScene(self)
        self._scale_scene.setItemIndexMethod(
            QGraphicsScene.ItemIndexMethod.NoIndex)
        self._scale_proxy = self._scale_scene.addWidget(self._surface)
        self._scale_proxy.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        self._scale_view = QGraphicsView(self._scale_scene, self)
        self._scale_view.setObjectName("ParserWindowScaleView")
        self._scale_view.setFrameShape(QFrame.Shape.NoFrame)
        self._scale_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scale_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scale_view.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # UI and classic-EQ pixel art should remain sharply aligned. Smooth
        # pixmap interpolation made the complete scaled surface look soft.
        self._scale_view.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing)
        self._scale_view.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._scale_view.setOptimizationFlag(
            QGraphicsView.OptimizationFlag.DontSavePainterState, True)
        self._scale_view.setStyleSheet(
            "QGraphicsView#ParserWindowScaleView {"
            "background: transparent; border: none; padding: 0; }")
        self._scale_view.viewport().setMouseTracking(True)
        self._scale_view.viewport().installEventFilter(self)
        outer.addWidget(self._scale_view)
        self._logical_surface_width = self._design_size.width()
        self._logical_surface_height = self._design_size.height()
        self._native_resize_session = False
        self._panel_resize_state = None
        self._resize_handles = {
            direction: ParserResizeHandle(direction, self)
            for direction in ParserResizeHandle.CURSORS
        }
        # Compatibility alias for older callers. The lower-right handle is now
        # one of eight resize affordances instead of the only one.
        self._size_grip = self._resize_handles["bottom_right"]
        for handle in self._resize_handles.values():
            handle.hide()

        self.setGeometry(
            self._geometry[0], self._geometry[1],
            self._geometry[2], self._geometry[3])
        self.setObjectName("ParserWindow")
        self.setWindowOpacity(self._window_opacity / 100)
        self.setWindowTitle(self.name.title())

        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(450)
        self._geometry_save_timer.timeout.connect(self._save_geometry)

        self._header_pack_timer = QTimer(self)
        self._header_pack_timer.setSingleShot(True)
        self._header_pack_timer.timeout.connect(self._pack_header_controls)
        self._header_overflowed = []
        self._packing_header = False

        self._set_flags()

        QApplication.instance()._signals["settings"].config_updated.connect(
            self._parser_settings_config_update_watcher
        )
        QApplication.instance().aboutToQuit.connect(self._save_geometry)
        # One shared router handles right-clicks for every parser. Previously
        # each parser observed every application event, multiplying startup and
        # runtime work by the number of open panels.
        application = QApplication.instance()
        router = getattr(application, "_parser_context_router", None)
        if router is None:
            router = ParserContextMenuRouter(application)
            application._parser_context_router = router
        router.register(self)

    def finish_startup(self, show_on_launch=None):
        """Restore geometry without forcing every tool onto the desktop."""
        self._compact_header_controls()
        self._set_scaled_minimum_size()
        self._fit_to_available_screen()
        self._update_uniform_scale()
        if show_on_launch is False:
            # The Quick Bar is the launcher. Other tools remain fully loaded
            # but hidden, avoiding startup taskbar flashes and preserving their
            # saved geometry for the first click on the bar.
            self._toggled = False
            return
        if show_on_launch is True:
            self._toggled = True
            self.show()
            return
        startup_state = config.data.get('general', {}).get(
            'startup_window_state', 'rolled')
        if startup_state == 'rolled':
            self._set_collapsed(True)
        elif startup_state == 'minimized':
            # Preserve the configured window set for a future normal/rolled
            # launch, while reporting the true current visibility in the tray.
            self._toggled = False
            return
        if self._toggled:
            self.show()

    def _compact_header_controls(self):
        """Keep authored header icons inside the shared compact metrics."""
        if not self._parser_menu_area:
            return
        for control in self._parser_menu_area.findChildren(QAbstractButton):
            if not control.icon().isNull():
                control.setIconSize(QSize(13, 13))
        self._schedule_header_pack()

    @staticmethod
    def _scaled_header_metric(value, factor):
        value = max(0, int(value))
        return max(0, int(round(value * factor)))

    def _remember_header_widget_metrics(self, widget):
        """Capture native header metrics once, before compensating scaling."""
        if widget in self._header_widget_metrics:
            return self._header_widget_metrics[widget]
        hint = widget.sizeHint()
        icon_size = (
            widget.iconSize() if isinstance(widget, QAbstractButton) else
            QSize())
        metrics = {
            "minimum_width": widget.minimumWidth(),
            "maximum_width": widget.maximumWidth(),
            "minimum_height": widget.minimumHeight(),
            "maximum_height": widget.maximumHeight(),
            "hint_width": max(0, hint.width() if hint.isValid() else 0),
            "hint_height": max(0, hint.height() if hint.isValid() else 0),
            "font_pixels": max(1, widget.fontInfo().pixelSize()),
            "icon_width": max(0, icon_size.width()),
            "icon_height": max(0, icon_size.height()),
        }
        self._header_widget_metrics[widget] = metrics
        return metrics

    def _update_header_scale_compensation(self, surface_scale):
        """Keep opted-in title chrome crisp while the body remains scaled.

        Metrics are enlarged inside the logical replica by the inverse of the
        view transform. After QGraphicsView applies that transform, the header
        lands at its authored physical size rather than becoming microscopic.
        """
        if not self._keep_header_readable or not getattr(self, "_menu", None):
            return
        surface_scale = max(.01, float(surface_scale or 1.0))
        factor = 1.0 / min(1.0, surface_scale)
        self._header_metric_factor = factor

        def scaled_margins(values):
            return tuple(self._scaled_header_metric(value, factor)
                         for value in values)

        self._menu_content.setContentsMargins(
            *scaled_margins(self._header_root_base_margins))
        self._menu_content.setSpacing(max(
            1, self._scaled_header_metric(
                self._header_root_base_spacing, factor)))
        self.menu_area.setContentsMargins(
            *scaled_margins(self._header_menu_base_margins))
        self.menu_area.setSpacing(max(
            1, self._scaled_header_metric(
                self._header_menu_base_spacing, factor)))

        widgets = [self._menu, *self._menu.findChildren(QWidget)]
        for widget in widgets:
            if isinstance(widget, QMenu) or widget is self._title_icon:
                continue
            metrics = self._remember_header_widget_metrics(widget)
            font = widget.font()
            font.setPixelSize(max(
                1, self._scaled_header_metric(
                    metrics["font_pixels"], factor)))
            widget.setFont(font)

            if isinstance(widget, QAbstractButton):
                if factor <= 1.001:
                    widget.setMinimumSize(
                        metrics["minimum_width"],
                        metrics["minimum_height"])
                    widget.setMaximumSize(
                        metrics["maximum_width"],
                        metrics["maximum_height"])
                else:
                    base_width = max(
                        metrics["minimum_width"], min(
                            metrics["hint_width"],
                            metrics["maximum_width"]))
                    base_height = max(
                        metrics["minimum_height"], min(
                            metrics["hint_height"],
                            metrics["maximum_height"]))
                    width = max(
                        1, self._scaled_header_metric(base_width, factor))
                    height = max(
                        1, self._scaled_header_metric(base_height, factor))
                    widget.setFixedSize(width, height)
                if metrics["icon_width"] and metrics["icon_height"]:
                    widget.setIconSize(QSize(
                        max(1, self._scaled_header_metric(
                            metrics["icon_width"], factor)),
                        max(1, self._scaled_header_metric(
                            metrics["icon_height"], factor))))
            elif isinstance(widget, (QLineEdit, QComboBox, QAbstractSpinBox)):
                if factor <= 1.001:
                    widget.setMinimumSize(
                        metrics["minimum_width"],
                        metrics["minimum_height"])
                    widget.setMaximumSize(
                        metrics["maximum_width"],
                        metrics["maximum_height"])
                else:
                    base_width = max(
                        metrics["minimum_width"], metrics["hint_width"])
                    base_height = max(
                        metrics["minimum_height"], min(
                            metrics["hint_height"],
                            metrics["maximum_height"]))
                    widget.setMinimumWidth(max(
                        1, self._scaled_header_metric(base_width, factor)))
                    height = max(
                        1, self._scaled_header_metric(base_height, factor))
                    widget.setMinimumHeight(height)
                    widget.setMaximumHeight(height)

        # The title artwork is rasterized at the inverse logical size so the
        # final transformed icon still resolves to a crisp authored 14 px.
        icon_width = max(1, self._scaled_header_metric(15, factor))
        self._title_icon.setMinimumWidth(icon_width)
        self._title_icon.setMaximumWidth(icon_width)
        self._refresh_title_icon()
        self.menu_area.invalidate()
        self._menu_content.invalidate()
        self.menu_area.activate()
        self._menu_content.activate()
        self._pack_header_controls()

    def _schedule_header_pack(self):
        timer = getattr(self, "_header_pack_timer", None)
        if timer is not None and not self._packing_header:
            timer.start(0)

    def _header_menu_widgets(self):
        widgets = []
        for index in range(self.menu_area.count()):
            widget = self.menu_area.itemAt(index).widget()
            if widget is not None:
                widgets.append(widget)
        return widgets

    @staticmethod
    def _header_widget_width(widget):
        hint = widget.sizeHint()
        minimum_hint = widget.minimumSizeHint()
        return max(
            0, widget.minimumWidth(),
            hint.width() if hint.isValid() else 0,
            minimum_hint.width() if minimum_hint.isValid() else 0)

    def _header_menu_required_width(self, widgets):
        visible = [widget for widget in widgets if not widget.isHidden()]
        margins = self.menu_area.contentsMargins()
        width = margins.left() + margins.right()
        width += sum(self._header_widget_width(widget) for widget in visible)
        if len(visible) > 1:
            width += self.menu_area.spacing() * (len(visible) - 1)
        return width

    def _header_menu_available_width(self, overflow_visible=False):
        """Return the safe logical width left between title and chrome."""
        logical_width = max(
            1, getattr(self, "_logical_surface_width", 0),
            self._design_size.width())
        margins = self._menu_content.contentsMargins()
        fixed = (
            self._button, self._title_icon, self._settings_button,
            self._roll_button, self._minimize_button)
        fixed_width = sum(self._header_widget_width(widget) for widget in fixed)
        title_pixels = self._title.fontMetrics().horizontalAdvance(
            self._title.text()) + 5
        title_reserve = max(36, min(
            title_pixels, max(36, round(logical_width * 0.34))))
        self._title.setMinimumWidth(title_reserve)
        root_widgets = 7 + int(overflow_visible)
        root_spacing = self._menu_content.spacing() * (root_widgets - 1)
        overflow_width = (
            self._header_widget_width(self._header_overflow_button)
            if overflow_visible else 0)
        return max(
            0, logical_width - margins.left() - margins.right() -
            fixed_width - title_reserve - root_spacing - overflow_width)

    @staticmethod
    def _header_control_label(control):
        label = str(control.accessibleName() or "").strip()
        if not label:
            label = str(control.toolTip() or "").split("\n", 1)[0].strip()
        if not label:
            label = str(control.objectName() or "Window action").strip()
        return label

    def _header_overflow_candidates(self, widgets):
        candidates = []
        for index, widget in enumerate(widgets):
            if widget.isHidden():
                continue
            if widget.property("HeaderAlwaysVisible") is True:
                continue
            buttons = (
                [widget] if isinstance(widget, QAbstractButton) else
                widget.findChildren(QAbstractButton))
            if not buttons:
                # Live readouts, combo boxes and spin boxes remain in place.
                # Hiding an input would make the current value undiscoverable.
                continue
            try:
                priority = int(widget.property("HeaderPriority") or 0)
            except (TypeError, ValueError):
                priority = 0
            # Right-most actions are normally least frequent (clear, share,
            # mobile).  Explicit HeaderPriority can override that convention.
            candidates.append((priority, index, widget))
        return [item[2] for item in sorted(
            candidates, key=lambda item: (item[0], item[1]), reverse=True)]

    def _pack_header_controls(self):
        """Move lower-priority actions into one menu before any collision."""
        if self._packing_header or not hasattr(self, "_header_overflow_button"):
            return
        self._packing_header = True
        try:
            # Restore only controls hidden by this packer, then measure the
            # complete authored header again.  Subclass-hidden controls that
            # were never overflowed remain untouched.
            for widget in tuple(self._header_overflowed):
                try:
                    widget.show()
                except RuntimeError:
                    pass
            self._header_overflowed = []
            self._header_overflow_button.hide()
            self.menu_area.activate()
            self._menu_content.activate()

            widgets = self._header_menu_widgets()
            required = self._header_menu_required_width(widgets)
            focus_to_overflow = False
            if required > self._header_menu_available_width(False):
                available = self._header_menu_available_width(True)
                for widget in self._header_overflow_candidates(widgets):
                    focus = QApplication.focusWidget()
                    focus_to_overflow = focus_to_overflow or bool(
                        widget.hasFocus() or any(
                            child.hasFocus()
                            for child in widget.findChildren(QWidget)) or
                        focus is widget or
                        (focus is not None and widget.isAncestorOf(focus)))
                    widget.hide()
                    self._header_overflowed.append(widget)
                    required = self._header_menu_required_width(widgets)
                    if required <= available:
                        break
            self._header_overflow_button.setVisible(
                bool(self._header_overflowed))
            if focus_to_overflow and self._header_overflowed:
                self._header_overflow_button.setFocus()
            self._rebuild_header_overflow_menu()
            self.menu_area.activate()
            self._menu_content.activate()
            self._menu.updateGeometry()
        finally:
            self._packing_header = False

    def _add_header_button_to_overflow(self, menu, button):
        label = self._header_control_label(button)
        button_menu = button.menu() if isinstance(button, QToolButton) else None
        if button_menu is not None:
            submenu = menu.addMenu(button.icon(), label)
            submenu.setToolTipsVisible(True)
            submenu.menuAction().setToolTip(button.toolTip())
            if button.popupMode() != QToolButton.ToolButtonPopupMode.InstantPopup:
                primary = submenu.addAction(button.icon(), label)
                primary.setCheckable(button.isCheckable())
                primary.setChecked(button.isChecked())
                primary.setEnabled(button.isEnabled())
                primary.setToolTip(button.toolTip())
                primary.triggered.connect(
                    lambda _checked=False, control=button: control.click())
                submenu.addSeparator()
            for original in button_menu.actions():
                if original.isSeparator():
                    submenu.addSeparator()
                    continue
                proxy = submenu.addAction(original.icon(), original.text())
                proxy.setCheckable(original.isCheckable())
                proxy.setChecked(original.isChecked())
                proxy.setEnabled(original.isEnabled())
                proxy.setToolTip(original.toolTip())
                proxy.triggered.connect(
                    lambda _checked=False, action=original: action.trigger())
            return
        action = menu.addAction(button.icon(), label)
        action.setCheckable(button.isCheckable())
        action.setChecked(button.isChecked())
        action.setEnabled(button.isEnabled())
        action.setToolTip(button.toolTip())
        action.triggered.connect(
            lambda _checked=False, control=button: control.click())

    def _rebuild_header_overflow_menu(self):
        menu = getattr(self, "_header_overflow_menu", None)
        if menu is None:
            return
        menu.clear()
        for widget in self._header_overflowed:
            buttons = (
                [widget] if isinstance(widget, QAbstractButton) else
                widget.findChildren(QAbstractButton))
            if len(buttons) > 1:
                submenu = menu.addMenu(
                    self._header_control_label(widget))
                submenu.setToolTipsVisible(True)
                for button in buttons:
                    self._add_header_button_to_overflow(submenu, button)
            elif buttons:
                self._add_header_button_to_overflow(menu, buttons[0])

    def _parser_settings_config_update_watcher(self):
        requies_redraw = False

        settings_always_on_top = config.data.get(self.name, {}).get("always_on_top", True)
        settings_auto_hide_menu = config.data.get(self.name, {}).get("auto_hide_menu", True)
        settings_clickthrough = bool(
            self._allow_clickthrough and
            config.data.get(self.name, {}).get("clickthrough", False))
        settings_window_flush = config.data.get("general", {}).get("window_flush", True)
        settings_window_opacity = config.data.get(self.name, {}).get("opacity", 80)

        self._window_flush = settings_window_flush

        if self._clickthrough != settings_clickthrough:
            if self.isVisible():
                requies_redraw = True
            self._clickthrough = settings_clickthrough
            self._set_flags()

        if self._window_opacity != settings_window_opacity:
            self._window_opacity = settings_window_opacity
            self.setWindowOpacity(self._window_opacity / 100)

        if self._always_on_top != settings_always_on_top:
            if self.isVisible():
                requies_redraw = True
            self._always_on_top = settings_always_on_top
            self._set_flags()

        if self._auto_hide_menu != settings_auto_hide_menu:
            self._auto_hide_menu = settings_auto_hide_menu
            self._set_header_revealed(
                self._collapsed or not settings_auto_hide_menu)

        if requies_redraw:
            self.show()

    def _save_geometry(self):
        width = getattr(self, "_expanded_width", self.geometry().width()) \
            if self._collapsed else self.geometry().width()
        height = getattr(self, "_expanded_height", self.geometry().height()) \
            if self._collapsed else self.geometry().height()
        config.data[self.name]['geometry'] = [
            self.pos().x(), self.pos().y(),
            width, height
        ]
        config.save()

    def _schedule_geometry_save(self):
        if self.isVisible() and hasattr(self, "_geometry_save_timer"):
            self._geometry_save_timer.start()

    def _set_flags(self):
        if self._frameless:
            flags = Qt.WindowType.FramelessWindowHint
        else:
            flags = Qt.WindowType.WindowCloseButtonHint
            flags |= Qt.WindowType.WindowMinMaxButtonsHint
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self._clickthrough:
            flags |= Qt.WindowType.WindowTransparentForInput
        # Independent tray-controlled panels should never create one Windows
        # taskbar button each while the application is starting.
        flags |= Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self._sync_resize_handles()
        QTimer.singleShot(0, self._update_window_mask)

    def _set_header_revealed(self, revealed):
        revealed = bool(revealed)
        self._menu.show()
        # A QGraphicsEffect rasterizes its source even at 100% opacity. Keep
        # the visible header on Qt's native vector/text path and attach an
        # effect only while the header is deliberately invisible.
        if revealed:
            if self._menu.graphicsEffect() is not None:
                self._menu.setGraphicsEffect(None)
            self._menu_effect = None
        else:
            if self._menu.graphicsEffect() is None:
                self._menu_effect = QGraphicsOpacityEffect(self._menu)
                self._menu.setGraphicsEffect(self._menu_effect)
            self._menu_effect.setOpacity(0.0)
        self._menu.setEnabled(revealed)
        self._menu.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, not revealed)

    def _update_window_mask(self):
        if not self._frameless:
            self.clearMask()
            return
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 9, 9)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _toggle_frame(self):
        # QWidget.geometry() excludes native window chrome. Adjusting its top
        # by an estimated title-bar height made every framed -> frameless
        # conversion jump upward. QPoint/pos() is the outer top-left for a
        # top-level widget, so preserve that anchor and the client size across
        # the native-window recreation performed by setWindowFlags().
        anchor = QPoint(self.pos())
        client_size = QSize(self.size())
        was_visible = self.isVisible()
        self._frameless = not self._frameless
        self._set_flags()
        self._layout_resize_handles()
        self._sync_resize_handles()
        self.resize(client_size)
        self.move(anchor)
        if was_visible:
            self.show()
            self.move(anchor)
        expected_mode = self._frameless
        QTimer.singleShot(
            0, lambda point=QPoint(anchor), mode=expected_mode:
            self._restore_frame_anchor(point, mode))
        config.data[self.name]["frameless"] = self._frameless
        self._save_geometry()

    def _restore_frame_anchor(self, anchor, expected_frameless):
        """Finish a native frame change after Windows creates its new HWND."""
        if self._frameless != bool(expected_frameless):
            return
        self.move(QPoint(anchor))
        self._save_geometry()

    def eventFilter(self, watched, event):
        if (watched is self._scale_view.viewport()
                and event.type() == QEvent.Type.MouseMove):
            sync_scaled_hover_tooltip(
                self._scale_view, self._scale_proxy,
                self._surface, event.position().toPoint())
        if (watched is self._scale_view.viewport()
                and event.type() == QEvent.Type.ToolTip
                and forward_scaled_tooltip(
                    self._scale_view, self._scale_proxy,
                    self._surface, event)):
            return True
        if (watched is self._scale_view.viewport()
                and event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            self._focus_scaled_line_edit(event.position().toPoint())
        if (event.type() == QEvent.Type.ContextMenu
                and isinstance(watched, QWidget)
                and self._is_window_descendant(watched)
                and not self._preserve_child_context_menu(watched)):
            self._show_window_context_menu(event.globalPos())
            return True
        return super().eventFilter(watched, event)

    def event(self, event):
        result = super().event(event)
        if (event.type() in (
                QEvent.Type.DevicePixelRatioChange,
                QEvent.Type.ScreenChangeInternal)
                and getattr(self, "_title_icon", None) is not None):
            QTimer.singleShot(0, self._refresh_title_icon)
        return result

    def _refresh_title_icon(self):
        if getattr(self, "_title_icon", None) is None:
            return
        icon_size = max(1, self._scaled_header_metric(
            14, getattr(self, "_header_metric_factor", 1.0)))
        self._title_icon.setPixmap(game_pixmap(
            WINDOW_ICONS.get(self.name, "timer"), icon_size, self))

    def _focus_scaled_line_edit(self, viewport_position):
        """Give a scaled native editor reliable Windows keyboard focus.

        Qt normally forwards pointer focus through ``QGraphicsProxyWidget``,
        but Windows can leave the graphics viewport focused after activating a
        frameless always-on-top window.  Resolve the logical child under the
        pointer and explicitly focus an embedded line editor without
        consuming the original mouse event (so caret placement still works).
        """
        scene_position = self._scale_view.mapToScene(viewport_position)
        logical_position = self._scale_proxy.mapFromScene(scene_position)
        child = self._surface.childAt(logical_position.toPoint())
        while child and child is not self._surface:
            if isinstance(child, QLineEdit):
                self._restore_scaled_input_focus(child)
                QTimer.singleShot(
                    0, lambda editor=child:
                    self._restore_scaled_input_focus(editor))
                return
            child = child.parentWidget()

    def _restore_scaled_input_focus(self, editor):
        if not editor or not editor.isVisibleTo(self._surface):
            return
        self._scale_scene.setFocusItem(self._scale_proxy)
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def _is_window_descendant(self, widget):
        if widget.window() not in (self, self._surface):
            return False
        current = widget
        while current:
            if current in (self, self._surface):
                return True
            current = current.parentWidget()
        return False

    def _preserve_child_context_menu(self, widget):
        """Leave editing, buff-audio and map-specific menus untouched."""
        current = widget
        while current and current is not self:
            if isinstance(current, QLineEdit):
                return True
            if current.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu:
                return True
            if self.name == "maps" and current is getattr(self, "_map", None):
                return True
            current = current.parentWidget()
        return False

    def _build_window_context_menu(self):
        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        position_menu = menu.addMenu("Screen Position")
        position_actions = {}
        for label, anchor in (
                ("Top Left", ("left", "top")),
                ("Top Center", ("center", "top")),
                ("Top Right", ("right", "top")),
                ("Center Left", ("left", "center")),
                ("Center", ("center", "center")),
                ("Center Right", ("right", "center")),
                ("Bottom Left", ("left", "bottom")),
                ("Bottom Center", ("center", "bottom")),
                ("Bottom Right", ("right", "bottom"))):
            position_actions[position_menu.addAction(label)] = anchor

        layer_menu = menu.addMenu("Window Layer")
        always_top = layer_menu.addAction("Always on Top")
        always_top.setCheckable(True)
        always_top.setChecked(self._always_on_top)
        bring_front = layer_menu.addAction("Bring to Front Now")
        normal_layer = layer_menu.addAction("Normal Layer")
        send_back = layer_menu.addAction("Send to Back")

        opacity_menu = menu.addMenu("Transparency")
        opacity_actions = {}
        for opacity in (25, 40, 55, 70, 85, 100):
            action = opacity_menu.addAction(f"Opacity {opacity}%")
            action.setCheckable(True)
            action.setChecked(abs(self._window_opacity - opacity) <= 4)
            opacity_actions[action] = opacity

        menu.addSeparator()
        roll = menu.addAction(
            "Expand Panel" if self._collapsed else "Roll Up Panel")
        frame = menu.addAction(
            "Hide Windows Frame" if not self._frameless else
            "Show Windows Frame")
        recommended_size = menu.addAction("Restore Recommended Size")
        size_menu = menu.addMenu("Panel Size")
        size_actions = {}
        for label, scale in (
                ("Tiny replica · 25%", 0.25),
                ("Mini replica · 35%", 0.35),
                ("Compact replica · 50%", 0.50),
                ("Comfortable · 75%", 0.75),
                ("Original · 100%", 1.00)):
            size_action = size_menu.addAction(label)
            size_action.setToolTip(
                "Scale the complete panel without moving or reflowing its controls")
            size_actions[size_action] = scale
        minimize = menu.addAction("Hide in System Tray")
        window_settings = menu.addAction("Settings for This Window…")

        return menu, {
            "positions": position_actions,
            "always_top": always_top,
            "bring_front": bring_front,
            "normal_layer": normal_layer,
            "send_back": send_back,
            "opacities": opacity_actions,
            "roll": roll,
            "frame": frame,
            "recommended_size": recommended_size,
            "sizes": size_actions,
            "minimize": minimize,
            "window_settings": window_settings,
        }

    def _show_window_context_menu(self, global_position=None):
        menu, actions = self._build_window_context_menu()

        selected = menu.exec(global_position or QCursor.pos())
        if selected in actions["positions"]:
            self._move_to_screen_anchor(*actions["positions"][selected])
        elif selected == actions["always_top"]:
            self._set_always_on_top(actions["always_top"].isChecked())
        elif selected == actions["bring_front"]:
            self.show()
            self.raise_()
            self.activateWindow()
        elif selected == actions["normal_layer"]:
            self._set_always_on_top(False)
        elif selected == actions["send_back"]:
            self._set_always_on_top(False)
            self.lower()
        elif selected in actions["opacities"]:
            self._set_window_opacity(actions["opacities"][selected])
        elif selected == actions["roll"]:
            self._toggle_rollup()
        elif selected == actions["frame"]:
            self._toggle_frame()
        elif selected == actions["recommended_size"]:
            self._restore_recommended_size()
        elif selected in actions["sizes"]:
            self._set_replica_scale(actions["sizes"][selected])
        elif selected == actions["minimize"]:
            self._minimize_to_tray()
        elif selected == actions["window_settings"]:
            self._show_inline_settings()

    def _settings_section(self):
        return {
            "maps": "Maps", "spells": "Buffs & Triggers",
            "timers": "Smart Timers", "combat": "Combat",
            "heals": "Heal Chain", "market": "Market",
            "quickbar": "Quick Bar", "tick": "Appearance",
        }.get(self.name, "Appearance")

    def _show_inline_settings(self):
        """Expose each panel's common settings from the panel itself."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        always_top = menu.addAction("Always on Top")
        always_top.setCheckable(True)
        always_top.setChecked(self._always_on_top)
        auto_hide = menu.addAction("Auto-hide Header")
        auto_hide.setCheckable(True)
        auto_hide.setChecked(self._auto_hide_menu)
        clickthrough = None
        if self._allow_clickthrough:
            clickthrough = menu.addAction("Allow Click-through")
            clickthrough.setCheckable(True)
            clickthrough.setChecked(self._clickthrough)
            clickthrough.setToolTip(
                "Let mouse input pass through this window to EverQuest")
        background_audio = None
        if self.name in {"spells", "timers"}:
            background_audio = menu.addAction("Sound while Window Is Hidden")
            background_audio.setCheckable(True)
            background_audio.setChecked(bool(
                config.data[self.name].get("sounds_when_hidden", False)))
            background_audio.setToolTip(
                "Allow this tool's attributed alerts when its panel is hidden; "
                "master mute still blocks every sound")
        opacity_menu = menu.addMenu("Opacity")
        opacity_actions = {}
        for opacity in (25, 40, 55, 70, 85, 100):
            action = opacity_menu.addAction(f"{opacity}%")
            action.setCheckable(True)
            action.setChecked(abs(self._window_opacity - opacity) <= 4)
            opacity_actions[action] = opacity
        menu.addSeparator()
        section = self._settings_section()
        full_settings = menu.addAction(f"All {section} Settings…")
        full_settings.setIcon(game_icon("settings"))
        full_settings.setToolTip(
            f"Open the complete {section} settings page")
        selected = menu.exec(
            self._settings_button.mapToGlobal(
                self._settings_button.rect().bottomLeft()))
        if selected == always_top:
            self._set_always_on_top(always_top.isChecked())
        elif selected == auto_hide:
            self._auto_hide_menu = auto_hide.isChecked()
            config.data[self.name]["auto_hide_menu"] = self._auto_hide_menu
            self._set_header_revealed(
                self._collapsed or not self._auto_hide_menu)
            config.save()
        elif clickthrough is not None and selected == clickthrough:
            geometry = self.geometry()
            visible = self.isVisible()
            self._clickthrough = clickthrough.isChecked()
            config.data[self.name]["clickthrough"] = self._clickthrough
            self._set_flags()
            self.setGeometry(geometry)
            if visible:
                self.show()
            config.save()
        elif background_audio is not None and selected == background_audio:
            config.data[self.name]["sounds_when_hidden"] = \
                background_audio.isChecked()
            config.save()
        elif selected in opacity_actions:
            self._set_window_opacity(opacity_actions[selected])
        elif selected == full_settings:
            QApplication.instance().show_settings(section)

    def _set_always_on_top(self, enabled):
        geometry = self.geometry()
        visible = self.isVisible()
        self._always_on_top = bool(enabled)
        config.data[self.name]['always_on_top'] = self._always_on_top
        self._set_flags()
        self.setGeometry(geometry)
        if visible:
            self.show()
        config.save()

    def _set_window_opacity(self, opacity):
        self._window_opacity = max(25, min(100, int(opacity)))
        self.setWindowOpacity(self._window_opacity / 100)
        config.data[self.name]['opacity'] = self._window_opacity
        config.save()

    def _move_to_screen_anchor(self, horizontal, vertical):
        screen = QApplication.screenAt(QCursor.pos()) \
            or QApplication.screenAt(self.frameGeometry().center()) \
            or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        margin = 10
        width, height = self.width(), self.height()
        x_positions = {
            "left": area.left() + margin,
            "center": area.left() + max(0, (area.width() - width) // 2),
            "right": area.right() - width - margin + 1,
        }
        y_positions = {
            "top": area.top() + margin,
            "center": area.top() + max(0, (area.height() - height) // 2),
            "bottom": area.bottom() - height - margin + 1,
        }
        self.move(x_positions[horizontal], y_positions[vertical])
        self._save_geometry()

    def _restore_recommended_size(self):
        if self._collapsed:
            self._set_collapsed(False)
        self.resize(self._design_size)
        self._fit_to_available_screen()
        self._save_geometry()

    def _set_replica_scale(self, scale):
        if self._collapsed:
            self._set_collapsed(False)
        scale = max(self._effective_minimum_scale(), min(1.0, float(scale)))
        if self._minimum_readable_width:
            scale = max(scale, min(
                1.0,
                self._minimum_readable_width /
                max(1, self._design_size.width())))
        self.resize(
            round(self._design_size.width() * scale),
            round(self._design_size.height() * scale))
        self._fit_to_available_screen()
        self._save_geometry()

    def _set_design_size(self, size, preserve_scale=True):
        """Change a logical canvas without allowing its children to reflow."""
        size = QSize(size)
        size.setWidth(max(1, size.width()))
        size.setHeight(max(1, size.height()))
        if size == self._design_size:
            return
        old_size = QSize(self._design_size)
        scale = min(
            self.width() / max(1, old_size.width()),
            self.height() / max(1, old_size.height()))
        scale = max(self._effective_minimum_scale(), scale)
        self._design_size = size
        if not self._collapsed:
            self._logical_surface_width = size.width()
            self._logical_surface_height = size.height()
            self._surface.setFixedSize(size)
            self._resize_scale_proxy(size.width(), size.height())
            self._scale_scene.setSceneRect(QRectF(
                0, 0, size.width(), size.height()))
            self._set_scaled_minimum_size()
            if preserve_scale:
                self.resize(
                    round(size.width() * scale),
                    round(size.height() * scale))
                self._fit_to_available_screen()
            self._update_uniform_scale()
            self._schedule_header_pack()

    def _resize_scale_proxy(self, width, height):
        """Synchronize proxy constraints after its embedded canvas changes."""
        width, height = max(1, int(width)), max(1, int(height))
        self._scale_proxy.setMinimumSize(0, 0)
        self._scale_proxy.setMaximumSize(16777215, 16777215)
        self._scale_proxy.resize(width, height)
        self._scale_proxy.setPreferredSize(width, height)
        self._scale_proxy.setMinimumSize(width, height)
        self._scale_proxy.setMaximumSize(width, height)
        self._scale_proxy.setGeometry(QRectF(0, 0, width, height))

    def _start_move(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.windowHandle():
            self.windowHandle().startSystemMove()

    def _resize_handles_enabled(self):
        """Full/normal frameless panels resize directly from every edge."""
        return bool(
            self._frameless and not self._collapsed and
            not self._clickthrough)

    def _sync_resize_handles(self):
        handles = getattr(self, "_resize_handles", {})
        enabled = self._resize_handles_enabled()
        for handle in handles.values():
            handle.setVisible(enabled)
            if enabled:
                handle.raise_()

    def _layout_resize_handles(self):
        handles = getattr(self, "_resize_handles", {})
        if not handles:
            return
        thickness = 5
        corner = 11
        width, height = self.width(), self.height()
        handles["top"].setGeometry(
            corner, 0, max(1, width - 2 * corner), thickness)
        handles["bottom"].setGeometry(
            corner, max(0, height - thickness),
            max(1, width - 2 * corner), thickness)
        handles["left"].setGeometry(
            0, corner, thickness, max(1, height - 2 * corner))
        handles["right"].setGeometry(
            max(0, width - thickness), corner, thickness,
            max(1, height - 2 * corner))
        handles["top_left"].setGeometry(0, 0, corner, corner)
        handles["top_right"].setGeometry(
            max(0, width - corner), 0, corner, corner)
        handles["bottom_left"].setGeometry(
            0, max(0, height - corner), corner, corner)
        handles["bottom_right"].setGeometry(
            max(0, width - corner), max(0, height - corner),
            corner, corner)
        self._sync_resize_handles()

    def _start_panel_resize(self, direction, global_position):
        if not self._resize_handles_enabled():
            return
        rect = self.geometry()
        self._panel_resize_state = (
            str(direction), QPoint(global_position),
            (rect.x(), rect.y(), rect.width(), rect.height()))

    def _drag_panel_resize(self, global_position):
        if self._panel_resize_state is None:
            return
        direction, origin, geometry = self._panel_resize_state
        start_x, start_y, start_width, start_height = geometry
        delta = QPoint(global_position) - origin
        minimum_width, minimum_height = (
            self.minimumWidth(), self.minimumHeight())
        maximum_width, maximum_height = (
            self.maximumWidth(), self.maximumHeight())
        left, top = start_x, start_y
        width, height = start_width, start_height
        if "left" in direction:
            width = max(
                minimum_width,
                min(maximum_width, start_width - delta.x()))
            left = start_x + start_width - width
        elif "right" in direction:
            width = max(
                minimum_width,
                min(maximum_width, start_width + delta.x()))
        if "top" in direction:
            height = max(
                minimum_height,
                min(maximum_height, start_height - delta.y()))
            top = start_y + start_height - height
        elif "bottom" in direction:
            height = max(
                minimum_height,
                min(maximum_height, start_height + delta.y()))
        self.setGeometry(left, top, width, height)

    def _stop_panel_resize(self):
        if self._panel_resize_state is None:
            return
        self._panel_resize_state = None
        self._fit_to_available_screen()
        self._schedule_geometry_save()

    def _toggle_rollup(self):
        self._set_collapsed(not self._collapsed)

    def _set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        # Publish the state before either branch lays itself out. Subclass
        # minimum-canvas hooks must know that a rolled panel is header-only.
        self._collapsed = collapsed
        # Rolled headers are already rendered 1:1. Reset any inverse metrics
        # left by a narrow expanded replica before measuring its natural width.
        if collapsed:
            self._update_header_scale_compensation(1.0)
        if collapsed:
            self._pack_header_controls()
            self._expanded_width = max(
                getattr(self, "_expanded_width", 0), self.width())
            self._expanded_height = max(
                getattr(self, "_expanded_height", 0), self.height())
            self._expanded_minimum_width = self.minimumWidth()
            self._expanded_minimum_height = self.minimumHeight()
            for index in range(1, self.content.count()):
                widget = self.content.itemAt(index).widget()
                if widget:
                    widget.hide()
            self._set_header_revealed(True)
            # A rolled panel is a compact tool strip, not a full-width empty
            # canvas. Preserve the expanded size for restoration, but fit the
            # rolled window tightly around its actual controls and title.
            bar_height = max(24, self._menu.sizeHint().height())
            bar_width = self._compact_header_width()
            scaled_width = max(96, bar_width)
            self._logical_surface_height = bar_height
            self._logical_surface_width = bar_width
            self._surface.setFixedSize(bar_width, bar_height)
            self._resize_scale_proxy(bar_width, bar_height)
            self._scale_scene.setSceneRect(
                QRectF(0, 0, bar_width, bar_height))
            scaled_height = max(22, bar_height)
            self.setMinimumWidth(scaled_width)
            self.setMaximumWidth(scaled_width)
            self.setMinimumHeight(scaled_height)
            self.setMaximumHeight(scaled_height)
            self.resize(scaled_width, scaled_height)
            self._roll_button.setIcon(game_icon("expand"))
            self._roll_button.setAccessibleName("Expand panel")
            self._roll_button.setToolTip("Expand panel content")
        else:
            self.setMaximumWidth(16777215)
            self.setMinimumWidth(getattr(
                self, "_expanded_minimum_width", 1))
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(getattr(self, "_expanded_minimum_height", 1))
            self._logical_surface_width = self._design_size.width()
            self._logical_surface_height = self._design_size.height()
            self._surface.setFixedSize(self._design_size)
            self._resize_scale_proxy(
                self._design_size.width(), self._design_size.height())
            self._scale_scene.setSceneRect(QRectF(
                0, 0, self._design_size.width(),
                self._design_size.height()))
            for index in range(1, self.content.count()):
                widget = self.content.itemAt(index).widget()
                if widget:
                    widget.show()
            self.resize(max(
                getattr(self, "_expanded_width", 0), self.minimumWidth()), max(
                getattr(self, "_expanded_height", 0), self.minimumHeight()))
            self._roll_button.setIcon(game_icon("roll"))
            self._roll_button.setAccessibleName("Roll up panel")
            self._roll_button.setToolTip(
                "Roll up the panel and keep only its header")
            self._set_header_revealed(not self._auto_hide_menu)
        self._panel_resize_state = None
        self._sync_resize_handles()
        if not collapsed:
            self._set_scaled_minimum_size()
        self._update_uniform_scale()
        self._schedule_header_pack()
        config.data[self.name]["collapsed"] = collapsed
        self._save_geometry()

    def _compact_header_width(self):
        """Return the logical width required by the visible header only."""
        widgets = (
            self._button, self._title_icon, self._title,
            self._parser_menu_area, self._header_overflow_button,
            self._settings_button, self._roll_button, self._minimize_button)
        # Use explicit visibility so a panel rolled before its first show still
        # measures the controls it intends to reveal. QWidget.isVisible() is
        # false for every child while the top-level window is hidden.
        visible = [widget for widget in widgets if not widget.isHidden()]
        margins = self._menu_content.contentsMargins()
        width = margins.left() + margins.right()
        for widget in visible:
            if widget is self._title:
                width += self._title.fontMetrics().horizontalAdvance(
                    self._title.text()) + 6
            else:
                width += max(widget.minimumSizeHint().width(),
                             widget.sizeHint().width())
        if len(visible) > 1:
            width += self._menu_content.spacing() * (len(visible) - 1)
        # A rolled tool strip must be allowed to become wider than the expanded
        # design surface; capping it clipped or compressed dense header buttons.
        return max(96, width + 2)

    def _minimize_to_tray(self):
        self._save_geometry()
        self.hide()
        self._toggled = False
        config.data[self.name]['toggled'] = False
        config.save()

    def _fit_to_available_screen(self):
        """Keep restored geometry usable after monitor or DPI changes."""
        screen = QApplication.screenAt(self.frameGeometry().center()) \
            or QApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        if self._collapsed:
            width = min(max(96, self.width()), area.width())
            height = min(max(22, self.height()), area.height())
        else:
            width = min(max(self.minimumWidth(), self.width()), area.width())
            height = min(max(self.minimumHeight(), self.height()), area.height())
        left = min(max(area.left(), self.x()), area.right() - width + 1)
        top = min(max(area.top(), self.y()), area.bottom() - height + 1)
        self.setGeometry(left, top, width, height)

    def nativeEvent(self, event_type, message):
        """Constrain Windows' live drag rectangle before Qt lays it out."""
        if sys.platform == "win32":
            try:
                event_name = bytes(event_type)
            except (TypeError, ValueError):
                event_name = b""
            if event_name == b"windows_generic_MSG":
                try:
                    native_message = wintypes.MSG.from_address(int(message))
                    if native_message.message == WM_ENTERSIZEMOVE:
                        self._native_resize_session = True
                    elif (native_message.message == WM_SIZING
                          and not self._collapsed and native_message.lParam):
                        self._native_resize_session = True
                        rect_pointer = ctypes.cast(
                            int(native_message.lParam),
                            ctypes.POINTER(_WindowsRect))
                        rect = rect_pointer.contents
                        frame = self.frameGeometry()
                        constrained = independent_sizing_rect(
                            int(native_message.wParam),
                            (rect.left, rect.top, rect.right, rect.bottom),
                            self._design_size,
                            self._effective_minimum_scale(),
                            (
                                max(0, frame.width() - self.width()),
                                max(0, frame.height() - self.height())),
                            self.devicePixelRatioF(),
                            self._minimum_readable_width)
                        (rect.left, rect.top,
                         rect.right, rect.bottom) = constrained
                        return True, 1
                    elif native_message.message == WM_EXITSIZEMOVE:
                        self._native_resize_session = False
                        self._schedule_geometry_save()
                except (AttributeError, OSError, TypeError, ValueError):
                    # Let Qt handle an unfamiliar native payload. The fallback
                    # resizeEvent path below still keeps programmatic sizes sane.
                    pass
        return super().nativeEvent(event_type, message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_uniform_scale)
        self._schedule_header_pack()
        self._layout_resize_handles()
        self._update_window_mask()
        self._schedule_geometry_save()

    def _update_uniform_scale(self):
        """Scale by width while making height a real list viewport."""
        if self._scale_view and self._scale_proxy:
            logical_width = max(1, int(self._logical_surface_width))
            viewport = self._scale_view.viewport().size()
            scale = max(
                self._effective_minimum_scale(),
                viewport.width() / logical_width)
            self._update_header_scale_compensation(scale)
            logical_height = max(
                self._minimum_logical_surface_height(),
                int(round(viewport.height() / scale)))
            if logical_height != self._logical_surface_height:
                self._logical_surface_height = logical_height
                self._surface.setFixedSize(logical_width, logical_height)
                self._resize_scale_proxy(logical_width, logical_height)
            self._scale_scene.setSceneRect(QRectF(
                0, 0, logical_width, logical_height))
            self._scale_view.resetTransform()
            self._scale_view.scale(scale, scale)
            # Scrollbars are intentionally hidden, but QGraphicsView still
            # maintains their ranges when a vertically clipped logical canvas
            # is taller than the viewport. Pin those hidden ranges to the
            # origin so the header can never drift above the visible panel.
            self._scale_view.horizontalScrollBar().setValue(
                self._scale_view.horizontalScrollBar().minimum())
            self._scale_view.verticalScrollBar().setValue(
                self._scale_view.verticalScrollBar().minimum())
        self._layout_resize_handles()

    def _minimum_logical_surface_height(self):
        """Smallest canvas height a parser may lay out inside its viewport."""
        return 1

    def _set_scaled_minimum_size(self):
        if self._collapsed:
            return
        minimum_scale = self._effective_minimum_scale()
        self.setMinimumSize(
            max(round(self._design_size.width() * minimum_scale),
                int(self._minimum_readable_width)),
            round(self._design_size.height() * minimum_scale))

    def _effective_minimum_scale(self):
        return max(
            self._minimum_scale,
            72 / max(1, self._design_size.width()),
            48 / max(1, self._design_size.height()))

    def _coerce_to_logical_aspect(self):
        """Compatibility no-op: windows intentionally support free height."""

    def _aspect_size_for_resize(self, requested, previous):
        """Compatibility helper retained for older callers; preserve both axes."""
        return QSize(requested)

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_geometry_save()

    def toggle(self):
        if self.isVisible():
            self._save_geometry()
            self.hide()
            self._toggled = False
            config.data[self.name]['toggled'] = False
        else:
            self._fit_to_available_screen()
            self.show()
            self.raise_()
            self.activateWindow()
            self._toggled = True
            config.data[self.name]['toggled'] = True
        config.save()

    # Overrides QWidget to handle this event
    def closeEvent(self, _):
        if config.APP_EXIT:
            return
        # This is triggered if the user closes from the taskbar or from the X if the window is framed
        self._save_geometry()
        self._toggled = False
        config.data[self.name]['toggled'] = False
        config.save()

    # Overrides QWidget to handle this event
    def enterEvent(self, _):
        if self._auto_hide_menu:
            self._set_header_revealed(True)

    # Overrides QWidget to handle this event
    def leaveEvent(self, _):
        focused = QApplication.focusWidget()
        focus_in_menu = bool(
            focused and (
                focused is self._menu or self._menu.isAncestorOf(focused)))
        if self._auto_hide_menu and not self._collapsed and not focus_in_menu:
            self._set_header_revealed(False)
