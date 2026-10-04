from types import SimpleNamespace

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QApplication, QComboBox, QLineEdit, QPlainTextEdit, QSpinBox, QTextEdit,
    QVBoxLayout, QWidget)

from vantage.helpers.parser import ParserWindow, _text_editor_ancestor


def test_parser_preserves_native_right_click_menu_for_every_text_editor():
    app = QApplication.instance() or QApplication([])
    owner = SimpleNamespace(name="test")
    parent = QWidget()
    line = QLineEdit(parent)
    plain = QPlainTextEdit(parent)
    rich = QTextEdit(parent)

    assert ParserWindow._preserve_child_context_menu(owner, line)
    # Scroll-area context menu events arrive through the editor viewport.
    assert ParserWindow._preserve_child_context_menu(owner, plain.viewport())
    assert ParserWindow._preserve_child_context_menu(owner, rich.viewport())

    line.setText("editable")
    line.selectAll()
    standard = line.createStandardContextMenu()
    labels = {
        action.text().replace("&", "").split("\t", 1)[0]
        for action in standard.actions()}
    assert {"Cut", "Copy", "Paste", "Select All"}.issubset(labels)
    standard.deleteLater()
    parent.deleteLater()
    app.processEvents()


def test_editor_lookup_includes_editable_combo_and_spinbox_fields():
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    combo = QComboBox(parent)
    combo.setEditable(True)
    spin = QSpinBox(parent)

    assert _text_editor_ancestor(combo) is combo.lineEdit()
    assert _text_editor_ancestor(spin) is spin.lineEdit()
    parent.deleteLater()
    app.processEvents()


def test_scaled_panel_right_click_resolves_the_logical_text_editor(monkeypatch):
    app = QApplication.instance() or QApplication([])
    app._signals = {
        "settings": SimpleNamespace(
            config_updated=SimpleNamespace(connect=lambda *_: None))}
    monkeypatch.setattr(
        "vantage.helpers.parser.config.data",
        {"general": {"startup_window_state": "normal"}, "test": {}})
    monkeypatch.setattr("vantage.helpers.parser.config.save", lambda: None)
    panel = ParserWindow(name="test")
    layout = QVBoxLayout()
    editor = QLineEdit("copy and paste", panel._surface)
    layout.addWidget(editor)
    custom = QWidget(panel._surface)
    custom.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    custom.setMinimumHeight(30)
    layout.addWidget(custom)
    panel.content.addLayout(layout, 1)
    panel.resize(320, 180)
    panel.show()
    app.processEvents()

    logical_center = editor.rect().center()
    surface_position = editor.mapTo(panel._surface, logical_center)
    scene_position = panel._scale_proxy.mapToScene(surface_position)
    viewport_position = panel._scale_view.mapFromScene(scene_position)
    global_position = panel._scale_view.viewport().mapToGlobal(viewport_position)

    assert panel._scaled_text_editor_at_global(global_position) is editor

    custom_center = custom.rect().center()
    custom_surface_position = custom.mapTo(panel._surface, custom_center)
    custom_scene_position = panel._scale_proxy.mapToScene(custom_surface_position)
    custom_viewport_position = panel._scale_view.mapFromScene(custom_scene_position)
    custom_global_position = panel._scale_view.viewport().mapToGlobal(
        custom_viewport_position)
    mapped_custom = panel._scaled_child_at_global(custom_global_position)
    assert mapped_custom is custom
    assert panel._preserve_child_context_menu(mapped_custom)
    assert panel._scaled_text_editor_at_global(QPoint(-1000, -1000)) is None
    panel.close()
    panel.deleteLater()
    app.processEvents()


def test_scaled_right_click_routes_all_text_editors_before_the_panel_menu(
        monkeypatch):
    app = QApplication.instance() or QApplication([])
    app._signals = {
        "settings": SimpleNamespace(
            config_updated=SimpleNamespace(connect=lambda *_: None))}
    monkeypatch.setattr(
        "vantage.helpers.parser.config.data",
        {"general": {"startup_window_state": "normal"}, "test": {}})
    monkeypatch.setattr("vantage.helpers.parser.config.save", lambda: None)
    opened = []
    monkeypatch.setattr(
        "vantage.helpers.parser._show_standard_text_menu",
        lambda editor, point: opened.append((editor, point)))
    panel = ParserWindow(name="test")
    layout = QVBoxLayout()
    editors = (
        QLineEdit("line", panel._surface),
        QPlainTextEdit("plain", panel._surface),
        QTextEdit("rich", panel._surface),
    )
    for editor in editors:
        editor.setMinimumHeight(36)
        layout.addWidget(editor)
    panel.content.addLayout(layout, 1)
    panel.resize(320, 200)
    panel.show()
    app.processEvents()

    for editor in editors:
        surface_position = editor.mapTo(
            panel._surface, editor.rect().center())
        scene_position = panel._scale_proxy.mapToScene(surface_position)
        viewport_position = panel._scale_view.mapFromScene(scene_position)
        global_position = panel._scale_view.viewport().mapToGlobal(
            viewport_position)
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            viewport_position, global_position)
        QApplication.sendEvent(panel._scale_view.viewport(), event)

    assert [entry[0] for entry in opened] == list(editors)
    panel.close()
    panel.deleteLater()
    app.processEvents()
