import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QCursor, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QFrame, QGraphicsItem, QGraphicsOpacityEffect, QGraphicsScene, QGraphicsView, QSizeGrip,
    QSizePolicy, QVBoxLayout, QWidget)

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
        chrome=(0, 0), device_scale=1.0):
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
    minimum_width = max(1, int(round(
        logical_size.width() * dpr * float(minimum_scale))) + chrome_width)
    minimum_height = max(1, int(round(
        logical_size.height() * dpr * float(minimum_scale))) + chrome_height)

    if right - left < minimum_width:
        if edge in (WMSZ_LEFT, WMSZ_TOPLEFT, WMSZ_BOTTOMLEFT):
            left = right - minimum_width
        else:
            right = left + minimum_width
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

        self._parser_menu_area = QWidget()
        self._parser_menu_area.setObjectName("ParserWindowMenu")
        self._parser_menu_area.setLayout(self.menu_area)

        self._menu_content = QHBoxLayout()
        self._menu_content.setSpacing(2)
        # Keep controls clear of the 9 px rounded window mask. This margin is
        # part of the logical replica, so it remains proportional when scaled.
        self._menu_content.setContentsMargins(5, 0, 5, 0)
        self._menu_content.addWidget(self._button, 0)
        self._menu_content.addWidget(self._title_icon, 0)
        self._menu_content.addWidget(self._title, 1)
        self._menu_content.addWidget(self._parser_menu_area, 0)
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

        self.setGeometry(
            self._geometry[0], self._geometry[1],
            self._geometry[2], self._geometry[3])
        self.setObjectName("ParserWindow")
        self.setWindowOpacity(self._window_opacity / 100)
        self.setWindowTitle(self.name.title())

        self._size_grip = QSizeGrip(self)
        self._size_grip.setAccessibleName("Resize window")
        self._size_grip.setToolTip("Drag to resize")
        self._size_grip.resize(18, 18)

        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.setInterval(450)
        self._geometry_save_timer.timeout.connect(self._save_geometry)

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
        self._title_icon.setPixmap(game_pixmap(
            WINDOW_ICONS.get(self.name, "timer"), 14, self))

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

    def _toggle_rollup(self):
        self._set_collapsed(not self._collapsed)

    def _set_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed:
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
            self._size_grip.hide()
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
            self._size_grip.show()
            self._roll_button.setIcon(game_icon("roll"))
            self._roll_button.setAccessibleName("Roll up panel")
            self._roll_button.setToolTip(
                "Roll up the panel and keep only its header")
            self._set_header_revealed(not self._auto_hide_menu)
        self._collapsed = collapsed
        if not collapsed:
            self._set_scaled_minimum_size()
        self._update_uniform_scale()
        config.data[self.name]["collapsed"] = collapsed
        self._save_geometry()

    def _compact_header_width(self):
        """Return the logical width required by the visible header only."""
        widgets = (
            self._button, self._title_icon, self._title,
            self._parser_menu_area, self._roll_button,
            self._minimize_button)
        visible = [widget for widget in widgets if widget.isVisible()]
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
                            self.devicePixelRatioF())
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
            logical_height = max(1, int(round(viewport.height() / scale)))
            if logical_height != self._logical_surface_height:
                self._logical_surface_height = logical_height
                self._surface.setFixedSize(logical_width, logical_height)
                self._resize_scale_proxy(logical_width, logical_height)
            self._scale_scene.setSceneRect(QRectF(
                0, 0, logical_width, logical_height))
            self._scale_view.resetTransform()
            self._scale_view.scale(scale, scale)
        grip_size = max(8, round(14 * (
            1 if self._collapsed else self.width() /
            max(1, self._design_size.width()))))
        self._size_grip.resize(grip_size, grip_size)
        self._size_grip.move(
            self.width() - grip_size, self.height() - grip_size)

    def _set_scaled_minimum_size(self):
        if self._collapsed:
            return
        minimum_scale = self._effective_minimum_scale()
        self.setMinimumSize(
            round(self._design_size.width() * minimum_scale),
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
