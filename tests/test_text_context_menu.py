from types import SimpleNamespace

from PySide6.QtWidgets import (
    QApplication, QLineEdit, QPlainTextEdit, QTextEdit, QWidget)

from vantage.helpers.parser import ParserWindow


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
